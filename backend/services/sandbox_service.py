"""策略沙箱服务。

沙箱模式：使用真实实时行情数据运行策略，但不触发任何真实下单。
通过 mock OKXClient 拦截所有写操作（place_order / cancel_order / batch_place_orders），
返回虚拟订单 ID 并记录到内存；读操作（get_ticker / get_candles / get_balance /
get_positions）透传到真实 OKXClient。

与回测的区别：
- 沙箱：使用实时行情，策略按真实 tick 频率运行，验证策略在当前市场下的实时行为
- 回测：使用历史 K 线数据离线重放，验证策略在历史区间的表现

设计要点：
1. 不修改现有策略代码（GridStrategy / TrendStrategy / ComposableStrategy 等）
2. 使用独立的 MockOKXClient 包装真实 OKXClient，仅拦截写操作
3. 沙箱实例与真实策略实例完全隔离，不写入 DB 的 Order / PnlRecord 表
4. 虚拟订单与 PnL 曲线保存在内存，沙箱停止后可通过 result 接口查询
5. 沙箱任务用 asyncio.Task 管理，支持中途停止
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from services.okx_client import OKXClient

logger = logging.getLogger(__name__)


# ============================================================
# Mock OKXClient：拦截写操作，透传读操作
# ============================================================


class MockOKXClient:
    """包装真实 OKXClient，拦截所有写操作并返回虚拟结果。

    - place_order / batch_place_orders：生成虚拟订单 ID，记录到虚拟订单列表
    - cancel_order / cancel_all：在虚拟订单列表中标记 canceled
    - get_order / get_pending_orders：返回虚拟订单状态
    - get_ticker / get_candles / get_balance / get_positions：透传到真实 client

    属性：
        virtual_orders: 虚拟订单列表（按下单时间顺序）
        _order_index: 订单 ID -> 虚拟订单 dict 的索引
    """

    def __init__(self, real_client: OKXClient):
        self._real = real_client
        self.virtual_orders: list[dict] = []
        self._order_index: dict[str, dict] = {}
        self._order_counter = 0

    def _gen_order_id(self) -> str:
        """生成虚拟订单 ID（sandbox 前缀 + 计数器 + uuid 片段）。"""
        self._order_counter += 1
        return f"sandbox_{self._order_counter:06d}_{uuid.uuid4().hex[:8]}"

    async def place_order(
        self,
        inst_id: str,
        side: str,
        ord_type: str,
        sz: str,
        px: str | None = None,
    ) -> dict:
        """模拟下单：生成虚拟订单 ID，记录到虚拟订单列表。

        限价单状态为 live（挂单中），市价单状态为 filled（立即成交）。
        成交价：市价单用 None（由策略自行获取最新价），限价单用传入的 px。
        """
        order_id = self._gen_order_id()
        state = "filled" if ord_type == "market" else "live"
        order = {
            "ordId": order_id,
            "instId": inst_id,
            "side": side,
            "ordType": ord_type,
            "sz": sz,
            "px": px or "",
            "state": state,
            "fillPx": px if state == "filled" else "",
            "fillSz": sz if state == "filled" else "0",
            "fee": "0",
            "virtual": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.virtual_orders.append(order)
        self._order_index[order_id] = order

        logger.info(
            f"[sandbox] 虚拟下单: {side} {sz} {inst_id} @ {ord_type} "
            f"px={px} ordId={order_id} state={state}"
        )

        # 返回与真实 OKX API 一致的响应结构
        return {
            "code": "0",
            "msg": "",
            "data": [{"ordId": order_id, "sCode": "0", "sMsg": "虚拟下单成功"}],
        }

    async def batch_place_orders(self, orders: list[dict]) -> dict:
        """模拟批量下单：逐笔调用 place_order 并聚合结果。"""
        results = []
        for o in orders:
            resp = await self.place_order(
                inst_id=o.get("instId", ""),
                side=o.get("side", ""),
                ord_type=o.get("ordType", "limit"),
                sz=o.get("sz", "0"),
                px=o.get("px"),
            )
            results.extend(resp.get("data", []))
        return {"code": "0", "msg": "", "data": results}

    async def cancel_order(self, inst_id: str, order_id: str) -> dict:
        """模拟撤单：在虚拟订单列表中标记为 canceled。"""
        order = self._order_index.get(order_id)
        if order and order["state"] in ("live", "partially_filled"):
            order["state"] = "canceled"
            order["canceled_at"] = datetime.now(timezone.utc).isoformat()
            logger.info(f"[sandbox] 虚拟撤单: ordId={order_id}")
        return {"code": "0", "msg": "", "data": [{"ordId": order_id, "sCode": "0"}]}

    async def get_order(self, inst_id: str, order_id: str) -> list:
        """查询虚拟订单状态。"""
        order = self._order_index.get(order_id)
        if order:
            return [dict(order)]
        return []

    async def get_pending_orders(self, inst_id: str | None = None) -> list:
        """查询虚拟挂单（state=live）。"""
        return [
            dict(o)
            for o in self.virtual_orders
            if o["state"] in ("live", "partially_filled")
            and (inst_id is None or o["instId"] == inst_id)
        ]

    async def cancel_all(self, symbol: str) -> int:
        """撤销指定 symbol 的所有虚拟挂单。"""
        count = 0
        for o in self.virtual_orders:
            if o["instId"] == symbol and o["state"] in ("live", "partially_filled"):
                o["state"] = "canceled"
                o["canceled_at"] = datetime.now(timezone.utc).isoformat()
                count += 1
        if count:
            logger.info(f"[sandbox] 批量虚拟撤单: {symbol} 撤销 {count} 笔")
        return count

    # ---- 以下读操作透传到真实 OKXClient ----

    async def get_ticker(self, inst_id: str) -> list:
        return await self._real.get_ticker(inst_id)

    async def get_candles(self, inst_id: str, bar: str = "1m", limit: str = "100") -> list:
        return await self._real.get_candles(inst_id, bar=bar, limit=limit)

    async def get_balance(self) -> dict:
        return await self._real.get_balance()

    async def get_positions(self) -> list:
        return await self._real.get_positions()

    @property
    def public(self):
        """透传 public API（用于 funding_rate 等公开接口）。"""
        return self._real.public

    async def aclose(self):
        await self._real.aclose()


# ============================================================
# 沙箱运行结果
# ============================================================


class SandboxResult:
    """沙箱运行结果容器（内存存储）。"""

    def __init__(self, sandbox_id: str, symbol: str, qs_model_config: dict):
        self.sandbox_id = sandbox_id
        self.symbol = symbol
        self.qs_model_config = qs_model_config
        self.status: str = "pending"  # pending / running / completed / stopped / error
        self.started_at: str = ""
        self.ended_at: str = ""
        self.duration_seconds: float = 0.0
        self.virtual_orders: list[dict] = []
        self.pnl_curve: list[dict] = []  # [{ts, price, unrealized_pnl, realized_pnl, equity}]
        self.error: str = ""
        self.events: list[dict] = []  # 策略事件记录

    def to_dict(self) -> dict:
        return {
            "sandbox_id": self.sandbox_id,
            "symbol": self.symbol,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_seconds": round(self.duration_seconds, 2),
            "virtual_orders": list(self.virtual_orders),
            "pnl_curve": list(self.pnl_curve),
            "events": list(self.events[-50:]),  # 最近 50 条事件
            "error": self.error,
            "order_count": len(self.virtual_orders),
            "filled_count": sum(1 for o in self.virtual_orders if o.get("state") == "filled"),
            "canceled_count": sum(1 for o in self.virtual_orders if o.get("state") == "canceled"),
            "live_count": sum(1 for o in self.virtual_orders if o.get("state") == "live"),
        }


# ============================================================
# SandboxService 单例
# ============================================================


class SandboxService:
    """策略沙箱服务单例。

    - run_sandbox(qs_model_config, symbol, duration_seconds): 启动沙箱运行
    - get_status(sandbox_id): 查询沙箱状态
    - stop_sandbox(sandbox_id): 停止沙箱
    - get_result(sandbox_id): 获取沙箱结果

    沙箱实例保存在内存 _sandboxes 字典中，进程重启后丢失。
    """

    _instance: "SandboxService | None" = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._sandboxes: dict[str, tuple[asyncio.Task, SandboxResult, MockOKXClient]] = {}

    async def run_sandbox(
        self,
        qs_model_config: dict,
        symbol: str,
        duration_seconds: int = 300,
        tick_interval: float = 5.0,
        account_id: int | None = None,
    ) -> str:
        """启动沙箱运行策略。

        Args:
            qs_model_config: QS-Model 四段式配置（meta/params/logic/risk_filter）
            symbol: 交易对，如 BTC-USDT
            duration_seconds: 沙箱运行时长（秒），到期自动停止
            tick_interval: tick 间隔（秒），控制策略执行频率
            account_id: 可选账户 ID，用于获取真实行情（需要该账户有有效 API Key）

        Returns:
            sandbox_id: 沙箱实例 ID
        """
        sandbox_id = f"sandbox_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        result = SandboxResult(sandbox_id, symbol, qs_model_config)
        result.started_at = datetime.now(timezone.utc).isoformat()
        result.status = "running"

        # 构建真实 OKXClient 用于读取行情
        # 优先使用指定账户；无账户时尝试用第一个 demo 账户
        real_client = await self._build_real_client(account_id)
        if real_client is None:
            result.status = "error"
            result.error = "无可用的 OKX 账户用于读取行情，请先添加账户"
            result.ended_at = datetime.now(timezone.utc).isoformat()
            self._sandboxes[sandbox_id] = (None, result, None)  # type: ignore
            return sandbox_id

        mock_client = MockOKXClient(real_client)

        # 启动沙箱运行任务
        task = asyncio.create_task(
            self._run_sandbox_loop(
                sandbox_id=sandbox_id,
                result=result,
                mock_client=mock_client,
                qs_model_config=qs_model_config,
                symbol=symbol,
                duration_seconds=duration_seconds,
                tick_interval=tick_interval,
            )
        )
        self._sandboxes[sandbox_id] = (task, result, mock_client)

        logger.info(
            f"[sandbox] 沙箱已启动: id={sandbox_id} symbol={symbol} "
            f"duration={duration_seconds}s tick={tick_interval}s"
        )
        return sandbox_id

    async def _build_real_client(self, account_id: int | None) -> OKXClient | None:
        """构建真实 OKXClient 用于读取行情数据。

        优先使用指定 account_id；无指定时取第一个可用账户。
        """
        from database import SessionLocal
        from models.account import Account

        db = SessionLocal()
        try:
            if account_id is not None:
                account = db.query(Account).filter(Account.id == account_id).first()
            else:
                account = db.query(Account).first()
            if account is None:
                return None
            client = OKXClient(
                api_key_encrypted=account.api_key_encrypted,
                secret_encrypted=account.secret_key_encrypted,
                passphrase_encrypted=account.passphrase_encrypted,
                trade_mode=account.trade_mode,
                account_name=account.name,
            )
            return client
        finally:
            db.close()

    async def _run_sandbox_loop(
        self,
        sandbox_id: str,
        result: SandboxResult,
        mock_client: MockOKXClient,
        qs_model_config: dict,
        symbol: str,
        duration_seconds: int,
        tick_interval: float,
    ) -> None:
        """沙箱运行主循环。

        构建策略实例（使用 mock_client），按 tick_interval 循环执行 on_tick，
        每个 tick 记录 PnL 快照，直到 duration_seconds 到期或被停止。
        """
        start_ts = time.time()
        deadline = start_ts + duration_seconds

        try:
            # 构建策略实例
            strategy = await self._build_strategy(
                mock_client, qs_model_config, symbol, sandbox_id
            )
            if strategy is None:
                result.status = "error"
                result.error = "策略构建失败（未知策略类型或配置无效）"
                result.ended_at = datetime.now(timezone.utc).isoformat()
                return

            # 记录策略事件到沙箱结果
            self._patch_strategy_event_recording(strategy, result)

            # 启动策略
            try:
                await strategy.start()
            except Exception as e:
                logger.error(f"[sandbox] 策略启动失败: {e}", exc_info=True)
                result.status = "error"
                result.error = f"策略启动失败: {e}"
                result.ended_at = datetime.now(timezone.utc).isoformat()
                return

            # 循环执行 on_tick
            while time.time() < deadline and result.status == "running":
                try:
                    # 获取当前价格
                    current_price = await self._fetch_current_price(mock_client, symbol)

                    # 记录 PnL 快照
                    self._record_pnl_snapshot(result, strategy, current_price)

                    # 执行策略 tick（如果策略有 on_tick 钩子）
                    if hasattr(strategy, "on_tick"):
                        from dsl.context import ExecutionContext

                        ctx = ExecutionContext(
                            client=mock_client,
                            order_manager=strategy.order_manager,
                            base_strategy=getattr(strategy, "_base_block", None),
                            strategy=strategy,
                            instance_id=0,
                            account_id=0,
                            symbol=symbol,
                            tick_ts=time.time(),
                            current_price=current_price,
                        )
                        try:
                            await strategy.on_tick(ctx)
                        except Exception as e:
                            logger.warning(f"[sandbox] on_tick 异常: {e}")
                            result.events.append({
                                "type": "tick_error",
                                "message": str(e),
                                "ts": datetime.now(timezone.utc).isoformat(),
                            })
                    elif hasattr(strategy, "execute") and asyncio.iscoroutinefunction(strategy.execute):
                        # 非可拼接策略：execute 是主循环，沙箱不直接调用
                        # 仅依赖 start() 已启动的后台逻辑
                        pass

                    # 同步虚拟订单到结果
                    result.virtual_orders = list(mock_client.virtual_orders)

                except Exception as e:
                    logger.warning(f"[sandbox] tick 异常: {e}")
                    result.events.append({
                        "type": "tick_error",
                        "message": str(e),
                        "ts": datetime.now(timezone.utc).isoformat(),
                    })

                await asyncio.sleep(tick_interval)

            # 停止策略
            try:
                strategy.stop()
            except Exception as e:
                logger.warning(f"[sandbox] 策略停止异常: {e}")

            result.duration_seconds = time.time() - start_ts
            result.ended_at = datetime.now(timezone.utc).isoformat()
            result.virtual_orders = list(mock_client.virtual_orders)

            if result.status == "running":
                result.status = "completed"

            logger.info(
                f"[sandbox] 沙箱结束: id={sandbox_id} status={result.status} "
                f"orders={len(result.virtual_orders)} duration={result.duration_seconds:.1f}s"
            )

        except asyncio.CancelledError:
            result.status = "stopped"
            result.duration_seconds = time.time() - start_ts
            result.ended_at = datetime.now(timezone.utc).isoformat()
            result.virtual_orders = list(mock_client.virtual_orders)
            logger.info(f"[sandbox] 沙箱被手动停止: id={sandbox_id}")
            raise
        except Exception as e:
            result.status = "error"
            result.error = f"沙箱运行异常: {e}"
            result.duration_seconds = time.time() - start_ts
            result.ended_at = datetime.now(timezone.utc).isoformat()
            logger.error(f"[sandbox] 沙箱运行异常: {e}", exc_info=True)
        finally:
            try:
                await mock_client.aclose()
            except Exception:
                pass

    async def _build_strategy(
        self,
        mock_client: MockOKXClient,
        qs_model_config: dict,
        symbol: str,
        sandbox_id: str,
    ):
        """根据 qs_model_config 构建策略实例。

        优先构建 ComposableStrategy（支持 QS-Model），否则按 strategy_type
        映射到内置策略（grid / trend 等）。
        """
        from services.strategy_engine import strategy_engine
        from services.order_manager import OrderManager
        from database import SessionLocal

        # 从 qs_model_config 推断 strategy_type
        meta = qs_model_config.get("meta", {}) or {}
        logic = qs_model_config.get("logic", {}) or {}
        base_strategy_ref = logic.get("base_strategy", {}) or {}
        strategy_type = base_strategy_ref.get("kind", "composable")

        # 若 logic 中有 base_strategy.kind，则用 composable 包装
        if base_strategy_ref.get("kind"):
            strategy_type = "composable"

        strategy_cls = strategy_engine._strategy_map.get(strategy_type)
        if strategy_cls is None:
            logger.error(f"[sandbox] 未知策略类型: {strategy_type}")
            return None

        order_manager = OrderManager(SessionLocal, mock_client, 0, 0)

        # 构建 params
        params = {
            "qs_model_config": qs_model_config,
            "symbol": symbol,
        }

        try:
            strategy = strategy_cls(
                instance_id=0,
                params=params,
                client=mock_client,
                db_session_factory=SessionLocal,
                account_id=0,
                order_manager=order_manager,
                ws_client=None,
            )
            return strategy
        except Exception as e:
            logger.error(f"[sandbox] 策略实例化失败: {e}", exc_info=True)
            return None

    def _patch_strategy_event_recording(self, strategy, result: SandboxResult) -> None:
        """拦截策略的 _record_event，将事件记录到沙箱结果。"""
        original_record = strategy._record_event

        def patched_record(event_type: str, message: str, details: dict | None = None):
            result.events.append({
                "type": event_type,
                "message": message,
                "details": details,
                "ts": datetime.now(timezone.utc).isoformat(),
            })
            # 仍调用原始记录（写入 DB），但沙箱不关心 DB 数据
            try:
                original_record(event_type, message, details)
            except Exception:
                pass

        strategy._record_event = patched_record

    async def _fetch_current_price(self, client: MockOKXClient, symbol: str) -> float:
        """获取当前最新价。"""
        try:
            data = await client.get_ticker(symbol)
            if data:
                return float(data[0].get("last", "0"))
        except Exception as e:
            logger.warning(f"[sandbox] 获取价格失败: {e}")
        return 0.0

    def _record_pnl_snapshot(
        self, result: SandboxResult, strategy, current_price: float
    ) -> None:
        """记录 PnL 快照到结果曲线。"""
        realized = 0.0
        try:
            realized = float(strategy.get_realized_pnl())
        except Exception:
            pass

        # 虚拟持仓的未实现盈亏（简化：基于虚拟订单计算）
        unrealized = self._compute_virtual_unrealized_pnl(
            result.virtual_orders, current_price
        )

        snapshot = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "price": current_price,
            "realized_pnl": round(realized, 6),
            "unrealized_pnl": round(unrealized, 6),
            "total_pnl": round(realized + unrealized, 6),
        }
        result.pnl_curve.append(snapshot)

    def _compute_virtual_unrealized_pnl(
        self, orders: list[dict], current_price: float
    ) -> float:
        """基于虚拟订单计算未实现盈亏（简化版）。

        统计已成交的买单和卖单，计算净持仓与未实现盈亏。
        买单成交 = 增加持仓，卖单成交 = 减少持仓。
        未实现盈亏 = (当前价 - 加权平均成本) * 净持仓。
        """
        if current_price <= 0:
            return 0.0

        net_qty = 0.0
        total_cost = 0.0  # 买入总成本

        for o in orders:
            if o.get("state") != "filled":
                continue
            try:
                sz = float(o.get("fillSz") or o.get("sz") or 0)
                px = float(o.get("fillPx") or o.get("px") or 0)
            except (ValueError, TypeError):
                continue
            if sz <= 0:
                continue
            if o.get("side") == "buy":
                net_qty += sz
                total_cost += sz * px
            elif o.get("side") == "sell":
                net_qty -= sz
                # 卖出减少持仓成本（按加权平均）
                total_cost -= sz * px

        if abs(net_qty) < 1e-9:
            return 0.0

        avg_cost = total_cost / net_qty if net_qty != 0 else 0
        return (current_price - avg_cost) * net_qty

    # ---- 公开查询接口 ----

    def get_status(self, sandbox_id: str) -> dict | None:
        """查询沙箱状态。"""
        entry = self._sandboxes.get(sandbox_id)
        if entry is None:
            return None
        _, result, _ = entry
        return {
            "sandbox_id": result.sandbox_id,
            "symbol": result.symbol,
            "status": result.status,
            "started_at": result.started_at,
            "ended_at": result.ended_at,
            "duration_seconds": round(result.duration_seconds, 2),
            "order_count": len(result.virtual_orders),
            "pnl_point_count": len(result.pnl_curve),
            "error": result.error,
        }

    def get_result(self, sandbox_id: str) -> dict | None:
        """获取沙箱完整结果。"""
        entry = self._sandboxes.get(sandbox_id)
        if entry is None:
            return None
        _, result, _ = entry
        return result.to_dict()

    async def stop_sandbox(self, sandbox_id: str) -> dict | None:
        """停止沙箱运行。"""
        entry = self._sandboxes.get(sandbox_id)
        if entry is None:
            return None
        task, result, _ = entry
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if result.status == "running":
            result.status = "stopped"
            result.ended_at = datetime.now(timezone.utc).isoformat()
        return self.get_status(sandbox_id)

    def list_sandboxes(self) -> list[dict]:
        """列出所有沙箱实例状态。"""
        return [self.get_status(sid) for sid in self._sandboxes]  # type: ignore[misc]


# 单例
sandbox_service = SandboxService()
