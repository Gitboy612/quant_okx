from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base
from config import DATABASE_URL

engine = create_engine(
    DATABASE_URL.replace("+aiosqlite", "").replace("sqlite+aiosqlite", "sqlite"),
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def _migrate_strategy_templates_dsl_config():
    """确保 strategy_templates 表包含 dsl_config 列（向后兼容迁移）。

    SQLAlchemy ``create_all`` 只建新表不加列。已有库需要手动 ALTER TABLE。
    通过 inspector 检查列是否存在，缺失则添加，避免重复执行报错。
    """
    insp = inspect(engine)
    if "strategy_templates" not in insp.get_table_names():
        return
    existing_columns = {c["name"] for c in insp.get_columns("strategy_templates")}
    if "dsl_config" not in existing_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE strategy_templates ADD COLUMN dsl_config JSON"))
    # QS-Model v2.0 扩展列
    if "qs_model_config" not in existing_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE strategy_templates ADD COLUMN qs_model_config JSON"))
    if "logic_hash" not in existing_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE strategy_templates ADD COLUMN logic_hash VARCHAR"))


def _migrate_strategy_instances_logic_hash():
    """确保 strategy_instances 表包含 logic_hash 列（向后兼容迁移）。"""
    insp = inspect(engine)
    if "strategy_instances" not in insp.get_table_names():
        return
    existing_columns = {c["name"] for c in insp.get_columns("strategy_instances")}
    if "logic_hash" not in existing_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE strategy_instances ADD COLUMN logic_hash VARCHAR"))


def _migrate_pnl_records_is_final():
    """确保 pnl_records 表包含 is_final 列（向后兼容迁移）。"""
    insp = inspect(engine)
    if "pnl_records" not in insp.get_table_names():
        return
    existing_columns = {c["name"] for c in insp.get_columns("pnl_records")}
    if "is_final" not in existing_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE pnl_records ADD COLUMN is_final BOOLEAN DEFAULT 0 NOT NULL"))


def init_db():
    from models.user import User
    from models.account import Account
    from models.strategy import StrategyTemplate, StrategyInstance
    from models.order import Order
    from models.pnl import PnlRecord
    from models.log import OperationLog
    from models.api_call_log import ApiCallLog
    from models.setting import UserSetting
    from models.system_settings import SystemSetting
    from models.strategy_event import StrategyEvent

    Base.metadata.create_all(bind=engine)
    _migrate_strategy_templates_dsl_config()
    _migrate_strategy_instances_logic_hash()
    _migrate_pnl_records_is_final()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
