import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from services.okx_client import OKXClient
from database import SessionLocal


class BaseStrategy(ABC):
    def __init__(self, instance_id: int, params: dict, client: OKXClient, db_session_factory):
        self.instance_id = instance_id
        self.params = params
        self.client = client
        self.db_session_factory = db_session_factory
        self._running = False
        self._paused = False

    @abstractmethod
    async def execute(self):
        pass

    @abstractmethod
    async def validate_params(self) -> bool:
        pass

    def start(self):
        self._running = True
        self._paused = False

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def stop(self):
        self._running = False
        self._paused = False

    @property
    def is_running(self):
        return self._running and not self._paused

    @property
    def is_paused(self):
        return self._paused

    def record_order(self, symbol: str, side: str, order_type: str, price: float, quantity: float, order_id: str = "", status: str = "filled"):
        from models.order import Order
        db = self.db_session_factory()
        try:
            order = Order(
                strategy_instance_id=self.instance_id,
                account_id=None,
                symbol=symbol,
                order_id=order_id,
                side=side,
                order_type=order_type,
                price=price,
                quantity=quantity,
                filled_quantity=quantity,
                status=status,
            )
            db.add(order)
            db.commit()
        finally:
            db.close()

    def record_pnl(self, equity: float, unrealized_pnl: float, realized_pnl: float):
        from models.pnl import PnlRecord
        db = self.db_session_factory()
        try:
            record = PnlRecord(
                account_id=None,
                strategy_instance_id=self.instance_id,
                equity=equity,
                unrealized_pnl=unrealized_pnl,
                realized_pnl=realized_pnl,
                total_pnl=unrealized_pnl + realized_pnl,
            )
            db.add(record)
            db.commit()
        finally:
            db.close()

    def update_status(self, status: str):
        from models.strategy import StrategyInstance
        db = self.db_session_factory()
        try:
            instance = db.query(StrategyInstance).filter(StrategyInstance.id == self.instance_id).first()
            if instance:
                instance.status = status
                if status == "running":
                    instance.started_at = datetime.now(timezone.utc)
                elif status == "stopped":
                    instance.stopped_at = datetime.now(timezone.utc)
                db.commit()
        finally:
            db.close()
