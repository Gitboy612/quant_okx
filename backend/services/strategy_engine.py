import asyncio
from datetime import datetime, timezone
from database import SessionLocal
from services.okx_client import OKXClient
from models.strategy import StrategyTemplate, StrategyInstance
from models.account import Account
from strategies.grid_strategy import GridStrategy
from strategies.trend_strategy import TrendStrategy
from strategies.arbitrage_strategy import ArbitrageStrategy
from strategies.advanced_grid_hedge_strategy import AdvancedGridHedgeStrategy


class StrategyEngine:
    _instance = None
    _tasks: dict[int, asyncio.Task] = {}
    _strategy_map = {
        "grid": GridStrategy,
        "trend": TrendStrategy,
        "arbitrage": ArbitrageStrategy,
        "advanced_grid_hedge": AdvancedGridHedgeStrategy,
    }

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def check_feasibility(self, instance_id: int) -> dict:
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

            params = instance.params
            symbol = params.get("symbol", "")
            strategy_type = template.strategy_type

            tickers = client.get_ticker(symbol)
            if not tickers:
                return {"ok": False, "reason": f"无法获取 {symbol} 行情数据，请检查交易对是否存在"}

            current_price = float(tickers[0]["last"])

            if strategy_type == "grid":
                upper = params.get("upper_price", 0)
                lower = params.get("lower_price", 0)
                grid_count = params.get("grid_count", 0)
                order_qty = params.get("order_qty", 0)
                if upper <= lower or grid_count < 2 or order_qty <= 0:
                    return {"ok": False, "reason": "参数无效（上限>下限，网格数≥2，交易量>0）"}
                step = (upper - lower) / (grid_count - 1)
                grids_below = sum(1 for i in range(grid_count) if (lower + i * step) <= current_price)
                required_min = round(order_qty * grids_below * lower, 2)
                balance_resp = client.get_balance()
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
                    "reason": f"当前价{current_price}在[{lower}-{upper}]中，下方{grids_below}格需≈${required_min} USDT（买币+挂卖单），可用${available_usdt} USDT",
                }

            elif strategy_type in ("trend", "advanced_grid_hedge"):
                order_qty = params.get("order_qty", 0)
                if order_qty <= 0:
                    return {"ok": False, "reason": "交易量必须大于0"}
                if "-SWAP" in symbol:
                    balance_resp = client.get_balance()
                    available_usdt = self._extract_available(balance_resp, "USDT")
                    required = round(order_qty * current_price, 2)
                    return {"ok": available_usdt >= required * 0.2, "current_price": current_price,
                            "required_approx": required, "available_usdt": available_usdt,
                            "reason": f"约需${required}保证金，可用${available_usdt} USDT"}
                return {"ok": True, "current_price": current_price, "reason": "现货模式"}

            elif strategy_type == "arbitrage":
                return {"ok": True, "reason": "套利策略无需预检查"}

            return {"ok": True, "reason": "检查通过"}
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

            client = OKXClient(
                api_key_encrypted=account.api_key_encrypted,
                secret_encrypted=account.secret_key_encrypted,
                passphrase_encrypted=account.passphrase_encrypted,
                trade_mode=account.trade_mode,
                strategy_instance_id=instance.id,
                account_name=account.name,
            )

            strategy = strategy_cls(
                instance_id=instance.id,
                params=instance.params,
                client=client,
                db_session_factory=SessionLocal,
            )
            strategy.start()

            instance.status = "running"
            instance.started_at = datetime.now(timezone.utc)
            db.commit()

            task = asyncio.create_task(strategy.execute())
            self._tasks[instance_id] = (task, strategy)

        finally:
            db.close()

    async def pause_strategy(self, instance_id: int):
        entry = self._tasks.get(instance_id)
        if entry:
            entry[1].pause()
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
            entry[1].stop()
            entry[0].cancel()
            del self._tasks[instance_id]
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
        entry = self._tasks.get(instance_id)
        if entry:
            entry[1].params = params
        db = SessionLocal()
        try:
            instance = db.query(StrategyInstance).filter(StrategyInstance.id == instance_id).first()
            if instance:
                instance.params = params
                instance.updated_at = datetime.now(timezone.utc)
                db.commit()
        finally:
            db.close()

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
                        "symbol": {"label": "交易对", "type": "select", "default": "BTC-USDT", "options": ["BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT"]},
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
