from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import FRONTEND_DIR, CORS_ORIGINS
from spa_static import SPAStaticFiles

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
from routers.backtest import router as backtest_router
from routers.notifications import router as notifications_router
from routers.analytics import router as analytics_router
from routers.sandbox import router as sandbox_router
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
app.include_router(backtest_router)
app.include_router(notifications_router)
app.include_router(analytics_router)
app.include_router(sandbox_router)

if FRONTEND_DIR.exists():
    app.mount("/", SPAStaticFiles(directory=str(FRONTEND_DIR), html=True), name="static")


@app.on_event("startup")
async def startup():
    init_db()
    strategy_engine.seed_templates()

from models.user import User
from models.strategy import StrategyInstance
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

        # 启动恢复：保留 desired_status，标记 recovering，对账孤儿订单；
        # 不再盲目把 running/paused 改成 stopped（避免丢失用户意图）。
        try:
            recovery = await strategy_engine.recover_orphaned_instances()
            if recovery:
                print(f"[startup] Recovered {len(recovery)} strategy instance(s)")
        except Exception as e:
            print(f"[startup] recover_orphaned_instances failed: {e}")
            # 回退：至少不要让幽灵 running 状态残留
            orphaned = db.query(StrategyInstance).filter(
                StrategyInstance.status.in_(["running", "paused"])
            ).all()
            for inst in orphaned:
                if not getattr(inst, "desired_status", None):
                    inst.desired_status = inst.status
                inst.status = "recovering"
            if orphaned:
                db.commit()
                print(f"[startup] Fallback marked {len(orphaned)} instances as recovering")
    finally:
        db.close()


@app.on_event("shutdown")
async def shutdown():
    """关闭时清理 StrategyEngine 按账户缓存的 OKXClient，释放 httpx 连接。"""
    await strategy_engine.aclose()
