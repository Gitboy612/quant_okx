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


def _migrate_orders_columns():
    """补齐 orders 表的缺失列与索引（向后兼容迁移）。

    异地部署或旧版本库的 orders 表可能缺少 OKX V5 字段（cl_ord_id/fill_px 等）
    与 PnL 核算所需字段（pnl_accounted/ct_val 等）。此处统一补齐，与
    ``data/main.sql`` 参考标准对齐。
    """
    insp = inspect(engine)
    if "orders" not in insp.get_table_names():
        return
    existing_columns = {c["name"] for c in insp.get_columns("orders")}
    # 缺失列按 main.sql 顺序补齐（SQLite ALTER TABLE 只能追加到末尾，顺序由查询层不敏感）
    missing_defs = [
        ("cl_ord_id", "VARCHAR"),
        ("fill_px", "FLOAT"),
        ("fill_sz", "FLOAT"),
        ("fee", "FLOAT"),
        ("state", "VARCHAR"),
        ("update_time", "VARCHAR"),
        ("pnl_accounted", "BOOLEAN NOT NULL DEFAULT 0"),
        ("ct_val", "FLOAT"),
        ("ct_type", "VARCHAR"),
        ("settle_ccy", "VARCHAR"),
        ("actual_qty", "FLOAT"),
    ]
    with engine.begin() as conn:
        for col_name, col_type in missing_defs:
            if col_name not in existing_columns:
                conn.execute(text(f"ALTER TABLE orders ADD COLUMN {col_name} {col_type}"))
        # order_id 唯一约束（main.sql: UNIQUE "order_id" ASC）→ 用唯一索引实现
        existing_indexes = {i["name"] for i in insp.get_indexes("orders")}
        if "ix_orders_order_id_unique" not in existing_indexes:
            # 空表或无重复值时才能成功；若已有重复需人工处理
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ix_orders_order_id_unique "
                    'ON "orders" ("order_id" ASC)'
                )
            )
        # 复合索引：策略 PnL 核算高频查询（strategy_instance_id, status, pnl_accounted）
        if "ix_orders_strategy_status_accounted" not in existing_indexes:
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_orders_strategy_status_accounted "
                    "ON orders (strategy_instance_id, status, pnl_accounted)"
                )
            )


def _migrate_pnl_records_columns():
    """补齐 pnl_records 表的缺失列与索引（向后兼容迁移）。

    旧版本库可能缺少 net_position/avg_buy_price/total_fee/order_count 列，
    导致 PnL 核算引擎无法写入虚拟持仓与累计手续费。与 ``data/main.sql``
    参考标准对齐。
    """
    insp = inspect(engine)
    if "pnl_records" not in insp.get_table_names():
        return
    existing_columns = {c["name"] for c in insp.get_columns("pnl_records")}
    missing_defs = [
        ("net_position", "FLOAT"),
        ("avg_buy_price", "FLOAT"),
        ("total_fee", "FLOAT"),
        ("order_count", "INTEGER"),
    ]
    with engine.begin() as conn:
        for col_name, col_type in missing_defs:
            if col_name not in existing_columns:
                conn.execute(text(f"ALTER TABLE pnl_records ADD COLUMN {col_name} {col_type}"))
        # 复合索引：按策略+时间范围查询 PnL 曲线
        existing_indexes = {i["name"] for i in insp.get_indexes("pnl_records")}
        if "ix_pnl_records_strategy_recorded" not in existing_indexes:
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_pnl_records_strategy_recorded "
                    "ON pnl_records (strategy_instance_id, recorded_at)"
                )
            )


def _migrate_strategy_templates_logic_hash_index():
    """为 strategy_templates.logic_hash 创建索引（ORM 定义 index=True 但旧库未创建）。"""
    insp = inspect(engine)
    if "strategy_templates" not in insp.get_table_names():
        return
    existing_columns = {c["name"] for c in insp.get_columns("strategy_templates")}
    if "logic_hash" not in existing_columns:
        return  # 列都不存在，交给 _migrate_strategy_templates_dsl_config 处理
    existing_indexes = {i["name"] for i in insp.get_indexes("strategy_templates")}
    if "ix_strategy_templates_logic_hash" not in existing_indexes:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_strategy_templates_logic_hash "
                    "ON strategy_templates (logic_hash)"
                )
            )


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
    from models.notification_rule import NotificationRule

    Base.metadata.create_all(bind=engine)
    _migrate_strategy_templates_dsl_config()
    _migrate_strategy_instances_logic_hash()
    _migrate_pnl_records_is_final()
    _migrate_orders_columns()
    _migrate_pnl_records_columns()
    _migrate_strategy_templates_logic_hash_index()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
