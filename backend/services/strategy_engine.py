import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from database import SessionLocal
from services.okx_client import OKXClient
from models.strategy import StrategyTemplate, StrategyInstance
from models.account import Account
from strategies.grid_strategy import GridStrategy
from strategies.trend_strategy import TrendStrategy
from strategies.arbitrage_strategy import ArbitrageStrategy
from strategies.advanced_grid_hedge_strategy import AdvancedGridHedgeStrategy
from dsl.executor import ComposableStrategy
from fastapi import HTTPException
from services.pnl_accounting_engine import pnl_accounting_engine

logger = logging.getLogger(__name__)


def _compute_logic_hash_from_params(params: dict | None) -> str | None:
    """计算 params 中 logic 段的 SHA-256 哈希。

    优先取 qs_model_config.logic，回退到 dsl_config（向后兼容）。
    使用 sort_keys=True 规范化 JSON，确保相同内容产生相同哈希。
    与 routers/strategies.py 中 _compute_logic_hash 逻辑保持一致。
    """
    if not params:
        return None
    qs = params.get("qs_model_config")
    if qs:
        logic_source = qs.get("logic", {}) or {}
    else:
        logic_source = params.get("dsl_config")
    if logic_source is None:
        return None
    canonical_json = json.dumps(logic_source, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


class StrategyEngine:
    _instance = None
    _tasks: dict[int, tuple[asyncio.Task, object]] = {}
    _account_clients: dict[str, OKXClient] = {}
    _pnl_sampling_task: asyncio.Task | None = None
    _last_heartbeat_ts: dict[int, float] = {}
    # 同账户共享缓存：account_id -> (timestamp, data)，5 秒内复用
    _shared_balance_cache: dict[str, tuple[float, dict]] = {}
    _shared_positions_cache: dict[str, tuple[float, list]] = {}
    _shared_cache_ttl: float = 5.0
    _strategy_map = {
        "grid": GridStrategy,
        "trend": TrendStrategy,
        "arbitrage": ArbitrageStrategy,
        "advanced_grid_hedge": AdvancedGridHedgeStrategy,
        "composable": ComposableStrategy,
    }

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _get_client_for_strategy(self, strategy_instance_id: int) -> OKXClient | None:
        """从内存中的策略对象获取其使用的 OKXClient。"""
        entry = self._tasks.get(strategy_instance_id)
        if entry:
            _, strategy = entry
            return strategy.client
        return None

    async def get_shared_balance(self, account_id: int | str) -> dict:
        """获取同账户共享的余额缓存，5 秒内复用。

        同账户下多个策略实例共享余额查询结果，减少 OKX API 调用。
        缓存失败时回退到直接查询或返回过期缓存，不影响策略独立执行。
        """
        key = str(account_id)
        now = time.time()
        cached = self._shared_balance_cache.get(key)
        if cached and (now - cached[0] < self._shared_cache_ttl):
            return cached[1]
        client = self._account_clients.get(key)
        if client is None:
            # 账户未缓存 client，回退到过期缓存或空
            return cached[1] if cached else {}
        try:
            balance = await client.get_balance()
            self._shared_balance_cache[key] = (now, balance)
            return balance
        except Exception as e:
            logger.error(f"get_shared_balance error for account {key}: {e}")
            # 查询失败：回退到过期缓存或空，不抛出以隔离策略
            return cached[1] if cached else {}

    async def get_shared_positions(self, account_id: int | str) -> list:
        """获取同账户共享的持仓缓存，5 秒内复用。

        同账户下多个策略实例共享持仓查询结果，减少 OKX API 调用。
        缓存失败时回退到直接查询或返回过期缓存，不影响策略独立执行。
        """
        key = str(account_id)
        now = time.time()
        cached = self._shared_positions_cache.get(key)
        if cached and (now - cached[0] < self._shared_cache_ttl):
            return cached[1]
        client = self._account_clients.get(key)
        if client is None:
            return cached[1] if cached else []
        try:
            positions = await client.get_positions()
            self._shared_positions_cache[key] = (now, positions)
            return positions
        except Exception as e:
            logger.error(f"get_shared_positions error for account {key}: {e}")
            return cached[1] if cached else []

    def start_pnl_sampling(self):
        """启动 PnL 采样后台任务（若未运行或已完成则创建新任务）。"""
        if self._pnl_sampling_task is None or self._pnl_sampling_task.done():
            self._pnl_sampling_task = asyncio.create_task(self._pnl_sampling_loop())

    async def _pnl_sampling_loop(self):
        """PnL 采样循环：每 15s 对 running 策略执行增量核算，无成交时每 15s 写心跳快照。

        心跳间隔 15 秒，使盈亏曲线在约 75 分钟内累积 300+ 数据点。
        无成交时也写心跳记录，确保策略运行期间盈亏曲线有持续数据点。
        """
        while True:
            try:
                await asyncio.sleep(15)
                running_ids = self.get_running_ids()
                import time
                now_ts = time.time()
                for sid in running_ids:
                    try:
                        client = self._get_client_for_strategy(sid)
                        snapshot = await pnl_accounting_engine.incremental_update(sid, client)
                        if snapshot is not None:
                            # 有成交增量，重置心跳计时器
                            self._last_heartbeat_ts[sid] = now_ts
                        else:
                            # 无成交，检查是否需要心跳快照（≥15秒）
                            last_hb = self._last_heartbeat_ts.get(sid, 0)
                            if now_ts - last_hb >= 15:  # 15秒，确保盈亏曲线数据点密集
                                await pnl_accounting_engine.heartbeat_snapshot(sid, client)
                                self._last_heartbeat_ts[sid] = now_ts
                    except Exception as e:
                        logger.error(f"PnL sampling error for strategy {sid}: {e}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"PnL sampling loop error: {e}")
                await asyncio.sleep(10)  # 短暂等待后重试

    async def rebuild_pnl_baselines(self):
        """服务重启后重建 running 策略的 PnL 基准。

        查询 DB 中所有 status='running' 的策略实例（服务重启后内存丢失的情况），
        对每个实例调用 pnl_accounting_engine.recompute 重建基准。
        client 获取：优先用 _get_client_for_strategy（内存中已加载），
        否则用 _get_client_for_account 按账户构造。
        """
        db = SessionLocal()
        try:
            instances = (
                db.query(StrategyInstance)
                .filter(StrategyInstance.status == "running")
                .all()
            )
            instance_ids = [inst.id for inst in instances]
        finally:
            db.close()

        for instance_id in instance_ids:
            try:
                client = self._get_client_for_strategy(instance_id)
                if client is None:
                    # 内存中无此策略对象，按账户构造 client
                    db = SessionLocal()
                    try:
                        instance = (
                            db.query(StrategyInstance)
                            .filter(StrategyInstance.id == instance_id)
                            .first()
                        )
                        if instance:
                            account = (
                                db.query(Account)
                                .filter(Account.id == instance.account_id)
                                .first()
                            )
                            if account:
                                client = self._get_client_for_account(
                                    account, strategy_instance_id=instance_id
                                )
                    finally:
                        db.close()
                await pnl_accounting_engine.recompute(instance_id, client)
            except Exception as e:
                logger.error(f"rebuild_pnl_baselines error for strategy {instance_id}: {e}")

    def _get_client_for_account(self, account: "Account", strategy_instance_id: int | None = None) -> OKXClient:
        """按账户复用 OKXClient，避免每个实例/每次调用都新建连接导致句柄泄漏。

        同一账户（account.id）共享同一个 OKXClient；首次调用时按现有 start_strategy
        的参数构造并缓存。该方法为同步方法（OKXClient.__init__ 内部同步建连），
        asyncio 单线程下整段执行无 await，天然对并发启动安全。
        """
        key = str(account.id)
        client = self._account_clients.get(key)
        if client is None:
            client = OKXClient(
                api_key_encrypted=account.api_key_encrypted,
                secret_encrypted=account.secret_key_encrypted,
                passphrase_encrypted=account.passphrase_encrypted,
                trade_mode=account.trade_mode,
                strategy_instance_id=strategy_instance_id,
                account_name=account.name,
            )
            self._account_clients[key] = client
        return client

    async def aclose(self):
        """引擎关闭时取消采样任务并清理所有按账户缓存的 OKXClient，释放 httpx 连接。"""
        if self._pnl_sampling_task:
            self._pnl_sampling_task.cancel()
            try:
                await self._pnl_sampling_task
            except asyncio.CancelledError:
                pass
            self._pnl_sampling_task = None
        clients = list(self._account_clients.values())
        self._account_clients.clear()
        self._shared_balance_cache.clear()
        self._shared_positions_cache.clear()
        for client in clients:
            try:
                await client.aclose()
            except Exception:
                pass

    async def check_feasibility(self, instance_id: int) -> dict:
        db = SessionLocal()
        try:
            instance = db.query(StrategyInstance).filter(StrategyInstance.id == instance_id).first()
            if not instance:
                return {"ok": False, "reason": "策略实例不存在"}

            template = db.query(StrategyTemplate).filter(StrategyTemplate.id == instance.template_id).first()
            account = db.query(Account).filter(Account.id == instance.account_id).first()
            if not template or not account:
                return {"ok": False, "reason": "模板或账户不存在"}

            client = OKXClient(
                api_key_encrypted=account.api_key_encrypted,
                secret_encrypted=account.secret_key_encrypted,
                passphrase_encrypted=account.passphrase_encrypted,
                trade_mode=account.trade_mode,
                account_name=account.name,
            )

            try:
                params = instance.params
                symbol = params.get("symbol", "")
                strategy_type = template.strategy_type

                tickers = await client.get_ticker(symbol)
                if not tickers:
                    return {"ok": False, "reason": f"无法获取 {symbol} 行情数据，请检查交易对是否存在"}

                current_price = float(tickers[0]["last"])

                if strategy_type == "grid":
                    # 防御性类型转换：JSON 字段可能存储为字符串（用户输入或历史数据）
                    try:
                        upper = float(params.get("upper_price", 0))
                        lower = float(params.get("lower_price", 0))
                        grid_count = int(params.get("grid_count", 0))
                        order_qty = float(params.get("order_qty", 0))
                    except (TypeError, ValueError) as e:
                        return {"ok": False, "reason": f"参数类型无效: {e}"}
                    if upper <= lower or grid_count < 2 or order_qty <= 0:
                        return {"ok": False, "reason": "参数无效（上限>下限，网格数≥2，交易量>0）"}

                    # 自动校正：当前价不在网格区间内，或偏离中心超过 5% 时，以当前价为中心重算上下轨
                    grid_center = (upper + lower) / 2
                    deviation = abs(current_price - grid_center) / grid_center if grid_center > 0 else 1
                    grid_recalibrated = False
                    if current_price < lower or current_price > upper or deviation > 0.05:
                        # 以当前价为中心，保持原网格宽度，重算上下轨
                        grid_width = upper - lower
                        new_lower = round(current_price - grid_width / 2, 2 if "-SWAP" not in symbol else 1)
                        new_upper = round(current_price + grid_width / 2, 2 if "-SWAP" not in symbol else 1)
                        params["upper_price"] = new_upper
                        params["lower_price"] = new_lower
                        instance.params = params
                        db.commit()
                        upper, lower = new_upper, new_lower
                        grid_recalibrated = True
                        logger.info(
                            "策略#%s 网格自动校正: 中心价 %s → %s, [%s, %s]",
                            instance_id, grid_center, current_price, lower, upper,
                        )

                    step = (upper - lower) / (grid_count - 1)
                    grids_below = sum(1 for i in range(grid_count) if (lower + i * step) <= current_price)
                    required_min = round(order_qty * grids_below * lower, 2)
                    balance_resp = await client.get_balance()
                    available_usdt = self._extract_available(balance_resp, "USDT")
                    return {
                        "ok": available_usdt >= required_min * 0.3,
                        "current_price": current_price,
                        "upper_price": upper,
                        "lower_price": lower,
                        "grid_count": grid_count,
                        "grids_below_price": grids_below,
                        "required_usdt_min": required_min,
                        "available_usdt": available_usdt,
                        "grid_recalibrated": grid_recalibrated,
                        "reason": f"当前价{current_price}在[{lower}-{upper}]中，下方{grids_below}格需≈${required_min} USDT（买币+挂卖单），可用${available_usdt} USDT",
                    }

                elif strategy_type in ("trend", "advanced_grid_hedge"):
                    try:
                        order_qty = float(params.get("order_qty", 0))
                    except (TypeError, ValueError):
                        return {"ok": False, "reason": "交易量参数类型无效"}
                    if order_qty <= 0:
                        return {"ok": False, "reason": "交易量必须大于0"}
                    if "-SWAP" in symbol:
                        balance_resp = await client.get_balance()
                        available_usdt = self._extract_available(balance_resp, "USDT")
                        required = round(order_qty * current_price, 2)
                        return {"ok": available_usdt >= required * 0.2, "current_price": current_price,
                                "required_approx": required, "available_usdt": available_usdt,
                                "reason": f"约需${required}保证金，可用${available_usdt} USDT"}
                    return {"ok": True, "current_price": current_price, "reason": "现货模式"}

                elif strategy_type == "arbitrage":
                    return {"ok": True, "reason": "套利策略无需预检查"}

                return {"ok": True, "reason": "检查通过"}
            finally:
                await client.aclose()
        except Exception as e:
            return {"ok": False, "reason": f"检查异常: {str(e)}"}
        finally:
            db.close()

    def _extract_available(self, balance_resp: dict, ccy: str) -> float:
        try:
            for det in balance_resp.get("details", []):
                if det.get("ccy") == ccy:
                    return float(det.get("availBal", "0"))
        except Exception:
            pass
        return 0.0

    async def start_strategy(self, instance_id: int):
        db = SessionLocal()
        try:
            instance = db.query(StrategyInstance).filter(StrategyInstance.id == instance_id).first()
            if not instance:
                return

            template = db.query(StrategyTemplate).filter(StrategyTemplate.id == instance.template_id).first()
            account = db.query(Account).filter(Account.id == instance.account_id).first()
            if not template or not account:
                return

            strategy_cls = self._strategy_map.get(template.strategy_type)
            if not strategy_cls:
                return

            from services.encryption_service import decrypt

            client = self._get_client_for_account(account, strategy_instance_id=instance.id)

            # Create OrderManager
            from services.order_manager import OrderManager
            order_manager = OrderManager(SessionLocal, client, instance.id, account.id)

            # Create OKXWsClient
            from services.okx_ws_client import OKXWsClient
            ws_client = OKXWsClient(
                api_key=decrypt(account.api_key_encrypted),
                secret_key=decrypt(account.secret_key_encrypted),
                passphrase=decrypt(account.passphrase_encrypted) if account.passphrase_encrypted else "",
                trade_mode=account.trade_mode,
            )

            # 构建 params：若实例 params 未携带 dsl_config 但模板有，则合并进来，
            # 供 ComposableStrategy 从 self.params["dsl_config"] 读取。
            params = dict(instance.params)
            if "dsl_config" not in params and getattr(template, "dsl_config", None) is not None:
                params["dsl_config"] = template.dsl_config
            # 注入实例 logic_hash 供 ComposableStrategy 的 FSM 编译缓存复用
            if getattr(instance, "logic_hash", None) and "logic_hash" not in params:
                params["logic_hash"] = instance.logic_hash

            strategy = strategy_cls(
                instance_id=instance.id,
                params=params,
                client=client,
                db_session_factory=SessionLocal,
                account_id=account.id,
                order_manager=order_manager,
                ws_client=ws_client,
            )
            try:
                await strategy.start()
            except Exception as e:
                # 启动失败（网络错误、WebSocket 连接失败等）：标记实例为 error，
                # 记录日志并以 HTTPException 返回错误，避免 FastAPI 进程崩溃。
                logger.error(f"Strategy start failed: {e}", exc_info=True)
                instance.status = "error"
                db.commit()
                raise HTTPException(status_code=500, detail=f"策略启动失败: {e}")

            instance.status = "running"
            instance.started_at = datetime.now(timezone.utc)
            db.commit()

            task = asyncio.create_task(strategy.execute())
            self._tasks[instance_id] = (task, strategy)

            # 启动 PnL 采样后台任务（若尚未运行）
            self.start_pnl_sampling()

        finally:
            db.close()

    async def pause_strategy(self, instance_id: int):
        entry = self._tasks.get(instance_id)
        if entry:
            strategy = entry[1]
            # 暂停前先增量核算，确保最近成交被记录
            try:
                await pnl_accounting_engine.incremental_update(instance_id, strategy.client)
            except Exception as e:
                logger.error(f"pause_strategy incremental_update error for {instance_id}: {e}")
            strategy.pause()
        # Always update DB status, even if task not in memory (server restart)
        db = SessionLocal()
        try:
            instance = db.query(StrategyInstance).filter(StrategyInstance.id == instance_id).first()
            if instance:
                instance.status = "paused"
                db.commit()
        finally:
            db.close()

    async def resume_strategy(self, instance_id: int):
        entry = self._tasks.get(instance_id)
        if entry:
            entry[1].resume()
        db = SessionLocal()
        try:
            instance = db.query(StrategyInstance).filter(StrategyInstance.id == instance_id).first()
            if instance:
                instance.status = "running"
                db.commit()
        finally:
            db.close()

    async def stop_strategy(self, instance_id: int):
        entry = self._tasks.get(instance_id)
        if entry:
            task, strategy = entry
            # 停止前先增量核算，确保最后的成交被记录（strategy.stop 内部会 record_final_pnl）
            try:
                await pnl_accounting_engine.incremental_update(instance_id, strategy.client)
            except Exception as e:
                logger.error(f"stop_strategy incremental_update error for {instance_id}: {e}")
            strategy.stop()
            # Disconnect WebSocket
            if strategy.ws_client:
                await strategy.ws_client.disconnect()
            task.cancel()
            del self._tasks[instance_id]
        # Always update DB status, even if task not in memory
        db = SessionLocal()
        try:
            instance = db.query(StrategyInstance).filter(StrategyInstance.id == instance_id).first()
            if instance:
                instance.status = "stopped"
                instance.stopped_at = datetime.now(timezone.utc)
                db.commit()
        finally:
            db.close()

    async def update_params(self, instance_id: int, params: dict):
        """更新实例参数，检测 logic 段变化并按状态决定是否允许。

        - 计算「旧 params」与「新 params」的 logic 段 SHA-256（qs_model_config.logic
          优先，回退 dsl_config），对比是否变化。
        - 若 logic 变化且实例 status == "running"：拒绝并抛 HTTPException(400)，
          避免运行中改 logic 导致 FSM 与配置不一致。
        - 若 logic 变化且实例非 running（stopped/paused）：允许更新，并重新计算
          instance.logic_hash 字段。
        - 若 logic 未变化（仅改 params/meta/risk_filter 等）：自由更新，logic_hash 保持。
        - 运行中实例同步更新内存中策略对象的 params。
        """
        old_params = None
        db = SessionLocal()
        try:
            instance = db.query(StrategyInstance).filter(StrategyInstance.id == instance_id).first()
            if not instance:
                return
            old_params = instance.params
            old_logic_hash = _compute_logic_hash_from_params(old_params)
            new_logic_hash = _compute_logic_hash_from_params(params)
            logic_changed = old_logic_hash != new_logic_hash

            if logic_changed and instance.status == "running":
                raise HTTPException(
                    status_code=400,
                    detail="运行中不能修改 logic 结构，请停止后更新",
                )

            instance.params = params
            instance.updated_at = datetime.now(timezone.utc)
            if logic_changed:
                instance.logic_hash = new_logic_hash
            db.commit()
        finally:
            db.close()

        # 运行中实例：同步更新内存中策略对象的 params（逻辑未变，热更新参数）
        entry = self._tasks.get(instance_id)
        if entry:
            entry[1].params = params

    def get_strategy_status(self, instance_id: int) -> str | None:
        db = SessionLocal()
        try:
            instance = db.query(StrategyInstance).filter(StrategyInstance.id == instance_id).first()
            return instance.status if instance else None
        finally:
            db.close()

    def get_running_ids(self) -> list[int]:
        return [iid for iid, (task, _) in self._tasks.items() if not task.done()]

    def seed_templates(self):
        db = SessionLocal()
        try:
            db.query(StrategyTemplate).filter(StrategyTemplate.is_builtin == True).delete(synchronize_session=False)
            db.commit()

            templates = [
                StrategyTemplate(
                    name="网格交易",
                    strategy_type="grid",
                    description="在设定价格区间内均匀布置买卖网格，高抛低吸赚取波动收益",
                    default_params={"upper_price": 50000, "lower_price": 40000, "grid_count": 10, "order_qty": 0.01, "symbol": "BTC-USDT"},
                    param_schema={
                        "upper_price": {"label": "价格上限", "type": "number", "default": 50000, "min": 1, "step": 1, "hint": "网格价格区间的上限"},
                        "lower_price": {"label": "价格下限", "type": "number", "default": 40000, "min": 1, "step": 1, "hint": "网格价格区间的下限"},
                        "grid_count": {"label": "网格数量", "type": "number", "default": 10, "min": 2, "max": 200, "step": 1, "hint": "区间内布设的网格线条数，越多越密集"},
                        "order_qty": {"label": "单格交易量", "type": "number", "default": 0.01, "min": 0.0001, "step": 0.001, "hint": "每触及一格买卖的币数量"},
                        "symbol": {"label": "交易对", "type": "select", "default": "BTC-USDT", "options": ["BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT", "BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]},
                    },
                    is_builtin=True,
                ),
                StrategyTemplate(
                    name="趋势跟随",
                    strategy_type="trend",
                    description="基于双均线交叉信号判断趋势方向，顺势开仓",
                    default_params={"fast_ma_period": 5, "slow_ma_period": 20, "order_qty": 0.01, "symbol": "BTC-USDT-SWAP"},
                    param_schema={
                        "fast_ma_period": {"label": "快线周期", "type": "number", "default": 5, "min": 2, "max": 50, "step": 1, "hint": "快速均线计算周期，越小越灵敏"},
                        "slow_ma_period": {"label": "慢线周期", "type": "number", "default": 20, "min": 5, "max": 200, "step": 1, "hint": "慢速均线计算周期，越大越稳定"},
                        "order_qty": {"label": "单笔交易量", "type": "number", "default": 0.01, "min": 0.0001, "step": 0.001, "hint": "每次信号触发时的交易数量"},
                        "symbol": {"label": "交易对", "type": "select", "default": "BTC-USDT-SWAP", "options": ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]},
                    },
                    is_builtin=True,
                ),
                StrategyTemplate(
                    name="期现套利",
                    strategy_type="arbitrage",
                    description="监控现货与合约价差，价差超阈值时双向开仓套利",
                    default_params={"spot_symbol": "BTC-USDT", "futures_symbol": "BTC-USDT-SWAP", "spread_threshold": 1.0, "order_qty": 0.01},
                    param_schema={
                        "spot_symbol": {"label": "现货交易对", "type": "select", "default": "BTC-USDT", "options": ["BTC-USDT", "ETH-USDT", "SOL-USDT"]},
                        "futures_symbol": {"label": "合约交易对", "type": "select", "default": "BTC-USDT-SWAP", "options": ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]},
                        "spread_threshold": {"label": "价差阈值(%)", "type": "number", "default": 1.0, "min": 0.1, "max": 10, "step": 0.1, "hint": "价差超过此百分比时开仓套利"},
                        "order_qty": {"label": "单笔交易量", "type": "number", "default": 0.01, "min": 0.0001, "step": 0.001, "hint": "每腿下单数量"},
                    },
                    is_builtin=True,
                ),
                StrategyTemplate(
                    name="高级网格对冲",
                    strategy_type="advanced_grid_hedge",
                    description="网格套利升级版：币本位做多 + 上涨y%自动套保 + 下跌y%平套保 + 稳币紧急救险",
                    default_params={"y": 3, "n": 30, "order_qty": 0.01, "grid_count": 10, "safe_usdt": 100, "symbol": "BTC-USDT-SWAP"},
                    param_schema={
                        "y": {"label": "触发阈值(%)", "type": "number", "default": 3, "min": 0.5, "max": 20, "step": 0.5, "hint": "价格上涨y%触发套保，下跌y%平套保"},
                        "n": {"label": "套保比例(%)", "type": "number", "default": 30, "min": 5, "max": 100, "step": 5, "hint": "将网格利润的n%用于开一倍空套保"},
                        "order_qty": {"label": "单格交易量", "type": "number", "default": 0.01, "min": 0.0001, "step": 0.001, "hint": "网格每格买卖的币数量"},
                        "grid_count": {"label": "网格数量", "type": "number", "default": 10, "min": 2, "max": 200, "step": 1, "hint": "网格线数量，越多越密集"},
                        "safe_usdt": {"label": "救险储备(U)", "type": "number", "default": 100, "min": 10, "step": 10, "hint": "稳定币救险储备，接近强平价时自动补保证金"},
                        "symbol": {"label": "交易对", "type": "select", "default": "BTC-USDT-SWAP", "options": ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]},
                    },
                    is_builtin=True,
                ),
            ]
            db.add_all(templates)
            db.commit()
        finally:
            db.close()


strategy_engine = StrategyEngine()