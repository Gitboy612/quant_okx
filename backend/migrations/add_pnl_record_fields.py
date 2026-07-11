"""PnlRecord 表扩展迁移脚本。

为 pnl_records 表新增以下列（全部 nullable，向后兼容）：
- net_position  FLOAT   净持仓量（买入累计 - 卖出累计，基于 actual_qty）
- avg_buy_price FLOAT   加权平均买入价
- total_fee     FLOAT   累计手续费
- order_count   INTEGER 已核算的成交订单数

使用 sqlite3 直接连接数据库，对每列先检查是否存在再执行 ALTER TABLE，
可独立运行：python backend/migrations/add_pnl_record_fields.py
"""
import sqlite3
import sys
from pathlib import Path


def _resolve_db_path() -> Path:
    """解析数据库文件路径。

    优先复用 config.DATABASE_URL 以与运行时保持一致；
    若无法导入 config（例如独立运行环境），则按脚本相对位置推导：
    backend/migrations/add_pnl_record_fields.py -> 项目根/data/quant_okx.db
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from config import DATABASE_URL  # type: ignore

        url = DATABASE_URL
        for prefix in ("sqlite+aiosqlite:///", "sqlite:///", "sqlite:"):
            if url.startswith(prefix):
                url = url[len(prefix):]
                break
        if url:
            return Path(url)
    except Exception:
        pass

    project_root = Path(__file__).resolve().parent.parent.parent
    return project_root / "data" / "quant_okx.db"


NEW_COLUMNS = [
    ("net_position", "FLOAT"),
    ("avg_buy_price", "FLOAT"),
    ("total_fee", "FLOAT"),
    ("order_count", "INTEGER"),
]


def migrate(db_path: Path) -> None:
    if not db_path.exists():
        print(f"[migrate] 数据库文件不存在，跳过：{db_path}")
        return

    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(pnl_records)")
        existing = {row[1] for row in cursor.fetchall()}

        for col_name, col_type in NEW_COLUMNS:
            if col_name in existing:
                print(f"[migrate] 列已存在，跳过：{col_name}")
                continue
            stmt = f"ALTER TABLE pnl_records ADD COLUMN {col_name} {col_type}"
            cursor.execute(stmt)
            print(f"[migrate] 已添加列：{col_name} ({col_type})")

        conn.commit()
        print("[migrate] 迁移完成。")
    finally:
        conn.close()


def main() -> int:
    db_path = _resolve_db_path()
    print(f"[migrate] 数据库路径：{db_path}")
    migrate(db_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
