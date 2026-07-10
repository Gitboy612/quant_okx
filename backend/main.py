from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from config import FRONTEND_DIR, CORS_ORIGINS

from database import init_db
from routers.auth import router as auth_router
from routers.accounts import router as accounts_router
from routers.strategies import router as strategies_router
from routers.pnl import router as pnl_router
from routers.orders import router as orders_router
from routers.logs import router as logs_router
from routers.ws import router as ws_router
from routers.settings import router as settings_router
from routers.monitoring import router as monitoring_router
from routers.market import router as market_router
from routers.maintenance import router as maintenance_router
from routers.dsl import router as dsl_router
from services.strategy_engine import strategy_engine

app = FastAPI(title="QuantOKX", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(accounts_router)
app.include_router(strategies_router)
app.include_router(pnl_router)
app.include_router(orders_router)
app.include_router(logs_router)
app.include_router(ws_router)
app.include_router(settings_router)
app.include_router(monitoring_router)
app.include_router(market_router)
app.include_router(maintenance_router)
app.include_router(dsl_router)

if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="static")


@app.on_event("startup")
def startup():
    init_db()
    strategy_engine.seed_templates()

    from models.user import User
    from models.strategy import StrategyInstance
    from models.pnl import PnlRecord
    from services.auth_service import hash_password
    from database import SessionLocal

    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            admin = User(
                username="admin",
                password_hash=hash_password("admin123"),
                created_at=datetime.now(timezone.utc),
            )
            db.add(admin)
            db.commit()

        # Mark any running/paused strategies as stopped on server restart
        orphaned = db.query(StrategyInstance).filter(
            StrategyInstance.status.in_(["running", "paused"])
        ).all()
        for inst in orphaned:
            inst.status = "stopped"
            inst.stopped_at = datetime.now(timezone.utc)
        if orphaned:
            db.commit()
            # 重置状态后，为每个被重置实例写 unrealized=0 的 PnL 记录，避免仪表盘显示陈旧数据
            for instance in orphaned:
                latest_pnl = db.query(PnlRecord).filter(
                    PnlRecord.strategy_instance_id == instance.id
                ).order_by(PnlRecord.recorded_at.desc()).first()
                if latest_pnl:
                    new_record = PnlRecord(
                        account_id=instance.account_id,
                        strategy_instance_id=instance.id,
                        equity=latest_pnl.equity,
                        unrealized_pnl=0,
                        realized_pnl=latest_pnl.realized_pnl,
                        total_pnl=latest_pnl.realized_pnl,
                        recorded_at=datetime.now(timezone.utc),
                    )
                    db.add(new_record)
            db.commit()
            print(f"[startup] Reset {len(orphaned)} orphaned strategy instances to stopped")
    finally:
        db.close()


@app.on_event("shutdown")
async def shutdown():
    """关闭时清理 StrategyEngine 按账户缓存的 OKXClient，释放 httpx 连接。"""
    await strategy_engine.aclose()
