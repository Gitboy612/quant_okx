"""Accounting regressions against real isolated SQLite queries, never live data."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models.account import Account
from models.order import Order
from models.pnl import PnlRecord
from models.strategy import StrategyInstance, StrategyTemplate
from routers.pnl import get_pnl_summary
from services import pnl_accounting_engine as accounting


@pytest.fixture
def ledger(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(accounting, "SessionLocal", sessions)
    db = sessions()
    db.add(Account(id=1, name="test", api_key_encrypted="x", secret_key_encrypted="x"))
    db.add(StrategyTemplate(id=1, name="test", strategy_type="grid", default_params={}))
    db.add(StrategyInstance(id=1, template_id=1, account_id=1, name="test",
                           symbol="BTC-USDT", market_type="spot", params={"fee_rate": 0}))
    db.commit()
    yield db, accounting.PnlAccountingEngine()
    db.close()
    engine.dispose()


def trade(db, side, price, qty, *, status="filled", fee=0, fee_ccy=None):
    row = Order(strategy_instance_id=1, account_id=1, symbol="BTC-USDT", side=side,
                order_type="limit", status=status, fill_px=price, fill_sz=qty,
                actual_qty=qty, quantity=10, fee=fee, fee_ccy=fee_ccy,
                created_at=datetime.now(timezone.utc))
    db.add(row)
    db.commit()
    return row


def market(price):
    client = AsyncMock()
    client.get_ticker.return_value = [{"last": str(price)}]
    return client


@pytest.mark.asyncio
async def test_fifo_remaining_cost_and_opening_fee(ledger):
    db, engine = ledger
    trade(db, "buy", 100, 1, fee=-1, fee_ccy="USDT")
    trade(db, "buy", 120, 1, fee=-2, fee_ccy="USDT")
    trade(db, "sell", 130, 1, fee=-1, fee_ccy="USDT")
    snapshot = await engine.recompute(1, market(125))
    assert snapshot.realized_pnl == pytest.approx(28)
    assert snapshot.avg_buy_price == 120
    assert snapshot.unrealized_pnl == pytest.approx(3)
    assert snapshot.total_pnl == pytest.approx(31)


@pytest.mark.asyncio
async def test_short_and_position_reversal(ledger):
    db, engine = ledger
    trade(db, "sell", 120, 2)
    trade(db, "buy", 100, 3)
    snapshot = await engine.recompute(1, market(110))
    assert snapshot.realized_pnl == 40
    assert snapshot.net_position == 1
    assert snapshot.unrealized_pnl == 10
    assert snapshot.total_pnl == 50


@pytest.mark.asyncio
async def test_partial_canceled_and_repeated_updates(ledger):
    db, engine = ledger
    row = trade(db, "buy", 100, 0.25, status="partially_filled")
    first = await engine.incremental_update(1, market(120))
    assert first.total_pnl == 5
    row.fill_sz = row.actual_qty = 0.5
    row.status = "canceled"
    db.commit()
    second = await engine.incremental_update(1, market(120))
    repeated = await engine.heartbeat_snapshot(1, market(120))
    assert second.net_position == repeated.net_position == 0.5
    assert second.total_pnl == repeated.total_pnl == 10


@pytest.mark.asyncio
@pytest.mark.parametrize("price", [0, -1, "nan", "inf"])
async def test_missing_or_invalid_price_does_not_write_snapshot(ledger, price):
    db, engine = ledger
    trade(db, "buy", 100, 1)
    with pytest.raises(ValueError, match="current market price"):
        await engine.recompute(1, market(price))
    assert db.query(PnlRecord).count() == 0


@pytest.mark.asyncio
async def test_rebate_increases_profit_and_flat_needs_no_market(ledger):
    db, engine = ledger
    trade(db, "buy", 100, 1, fee=0.5, fee_ccy="USDT")
    trade(db, "sell", 110, 1, fee=-1, fee_ccy="USDT")
    snapshot = await engine.recompute(1)
    assert snapshot.realized_pnl == 9.5
    assert snapshot.total_fee == 0.5
    assert snapshot.unrealized_pnl == 0


def test_summary_includes_strategy_outside_latest_500_records(ledger):
    db, _ = ledger
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    db.add(PnlRecord(account_id=1, strategy_instance_id=2, realized_pnl=7,
                     unrealized_pnl=0, total_pnl=7, order_count=1, recorded_at=base))
    db.add_all([PnlRecord(account_id=1, strategy_instance_id=1, realized_pnl=3,
                         unrealized_pnl=0, total_pnl=3, order_count=1,
                         recorded_at=base + timedelta(seconds=i + 1)) for i in range(501)])
    db.commit()
    summary = get_pnl_summary(account_id=1, strategy_instance_id=None, db=db, user=None)
    assert summary["total_pnl"] == 10
    assert len(summary["by_strategy"]) == 2


@pytest.mark.asyncio
async def test_base_currency_fee_reduces_spot_inventory(ledger):
    db, engine = ledger
    trade(db, "buy", 100, 1, fee=-0.01, fee_ccy="BTC")
    snapshot = await engine.recompute(1, market(120))
    assert snapshot.net_position == pytest.approx(0.99)
    assert snapshot.total_fee == 1
    assert snapshot.total_pnl == pytest.approx(18.8)


@pytest.mark.asyncio
async def test_short_remaining_cost_and_fees(ledger):
    db, engine = ledger
    trade(db, "sell", 120, 2, fee=-2, fee_ccy="USDT")
    trade(db, "buy", 100, 1, fee=-1, fee_ccy="USDT")
    snapshot = await engine.recompute(1, market(110))
    assert snapshot.net_position == -1
    assert snapshot.realized_pnl == 18
    assert snapshot.unrealized_pnl == 9
    assert snapshot.total_pnl == 27


def test_websocket_uses_cumulative_execution_fields():
    from types import SimpleNamespace
    from unittest.mock import Mock
    from strategies.base_strategy import BaseStrategy
    strategy = SimpleNamespace(order_manager=Mock(), _record_event=Mock())
    BaseStrategy._on_ws_order_update(strategy, "order", "partially_filled", {
        "fillSz": "0.1", "accFillSz": "0.5", "fillPx": "120", "avgPx": "110",
        "fee": "-0.01", "feeCcy": "USDT",
    })
    kwargs = strategy.order_manager.update_order.call_args.kwargs
    assert kwargs["fillSz"] == "0.5"
    assert kwargs["fillPx"] == "110"
    assert kwargs["feeCcy"] == "USDT"


def test_legacy_order_schema_migration_is_repeatable(monkeypatch):
    import database
    from sqlalchemy import inspect, text
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE orders (id INTEGER PRIMARY KEY, order_id VARCHAR, strategy_instance_id INTEGER, status VARCHAR)"))
    monkeypatch.setattr(database, "engine", engine)
    database._migrate_orders_columns()
    database._migrate_orders_columns()
    assert "fee_ccy" in {column["name"] for column in inspect(engine).get_columns("orders")}
    engine.dispose()


@pytest.mark.asyncio
async def test_contract_quantity_fallback_and_unknown_currency(ledger):
    db, engine = ledger
    row = trade(db, "buy", 100, 10)
    row.actual_qty = None
    row.ct_val = 0.01
    db.commit()
    snapshot = await engine.recompute(1, market(120))
    assert snapshot.net_position == pytest.approx(0.1)
    assert snapshot.total_pnl == pytest.approx(2)
    row.fee = -1
    row.fee_ccy = "OTHER"
    db.commit()
    with pytest.raises(ValueError, match="unsupported fee currency"):
        await engine.recompute(1, market(120))
