from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from config import FRONTEND_DIR

from database import init_db
from routers.auth import router as auth_router
from routers.accounts import router as accounts_router
from routers.strategies import router as strategies_router
from routers.pnl import router as pnl_router
from routers.orders import router as orders_router
from routers.logs import router as logs_router
from routers.ws import router as ws_router
from routers.settings import router as settings_router
from services.strategy_engine import strategy_engine

app = FastAPI(title="QuantOKX", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"],
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

if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="static")


@app.on_event("startup")
def startup():
    init_db()
    strategy_engine.seed_templates()

    from models.user import User
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
    finally:
        db.close()
