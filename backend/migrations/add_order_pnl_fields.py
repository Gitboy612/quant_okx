"""一次性迁移脚本：为 orders 表添加 PnL 核算相关字段与索引。

SQLAlchemy 的 ``create_all`` 只建新表不加列，已有 SQLite 库需要手动 ALTER TABLE。
本脚本可独立运行：

    python backend/migrations/add_order_pnl_fields.py

新增字段：
    - pnl_accounted  BOOLEAN NOT NULL DEFAULT 0  是否已被增量核算处理
    - ct_val         FLOAT                       合约面值（如 0.01 BTC/张，现货为 1）
    - ct_type        VARCHAR                     合约类型：swap/forward/option，现货为 null
    - settle_ccy     VARCHAR                     结算币种，如 USDT
    - actual_qty     FLOAT                       实际交易量 = sz × ct_val

新增索引：
    - ix_orders_strategy_status_accounted ON orders (strategy_instance_id, status, pnl_accounted)

存量数据回填：
    - pnl_accounted 默认 0（False）
    - actual_qty：合约（symbol 含 -SWAP）用 quantity * ct_val（ct_val 缺失默认 1.0），
      现货直接用 quantity
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

# 将 backend 目录加入 sys.path，使脚本可独立运行
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


def _resolve_db_path() -> Path:
    """从 backend/config.py 解析 SQLite 数据库文件路径。"""
    try:
        from config import DATABASE_URL  # noqa: WPS433
    except ImportError as exc:
        raise RuntimeError(
            "无法导入 backend/config.py，请确保在项目根目录运行本脚本"
        ) from exc

    # DATABASE_URL 形如 "sqlite+aiosqlite:///E:/.../data/quant_okx.db"
    url = DATABASE_URL
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///", "sqlite+aiosqlite:", "sqlite:"):
        if url.startswith(prefix):
            url = url[len(prefix):]
            break
    # 去掉可能的前导斜杠差异，转为本地路径
    path = Path(url)
    return path


# 新增列定义： (列名, 完整 SQLite 类型定义)
_NEW_COLUMNS = [
    ("pnl_accounted", "BOOLEAN NOT NULL DEFAULT 0"),
    ("ct_val", "FLOAT"),
    ("ct_type", "VARCHAR"),
    ("settle_ccy", "VARCHAR"),
    ("actual_qty", "FLOAT"),
]

# 复合索引名与列定义
_INDEX_NAME = "ix_orders_strategy_status_accounted"
_INDEX_COLUMNS = "strategy_instance_id, status, pnl_accounted"


def _existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """通过 PRAGMA table_info 获取表已有列名集合。"""
    cur = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def _add_missing_columns(conn: sqlite3.Connection) -> list[str]:
    """为 orders 表添加缺失的新列，返回实际添加的列名列表。"""
    added: list[str] = []
    existing = _existing_columns(conn, "orders")
    for col_name, col_type in _NEW_COLUMNS:
        if col_name in existing:
            continue
        conn.execute(f"ALTER TABLE orders ADD COLUMN {col_name} {col_type}")
        added.append(col_name)
    return added


def _create_index(conn: sqlite3.Connection) -> bool:
    """创建复合索引（若已存在则跳过）。返回是否执行了创建。"""
    cur = conn.execute(
        f"SELECT name FROM sqlite_master WHERE type='index' AND name=?",
        (_INDEX_NAME,),
    )
    if cur.fetchone() is not None:
        return False
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS {_INDEX_NAME} ON orders ({_INDEX_COLUMNS})"
    )
    return True


def _backfill_actual_qty(conn: sqlite3.Connection) -> int:
    """回填存量订单的 actual_qty 字段。

    - 合约（symbol 含 -SWAP）：actual_qty = quantity * COALESCE(ct_val, 1.0)
    - 现货：actual_qty = quantity

    ct_val 在本地无法查询 OKX instrument 接口，缺失时按 1.0 处理。
    返回更新的行数。
    """
    cur = conn.execute(
        """
        UPDATE orders
        SET actual_qty = CASE
            WHEN symbol LIKE '%-SWAP' THEN
                COALESCE(quantity, 0) * COALESCE(ct_val, 1.0)
            ELSE
                COALESCE(quantity, 0)
        END
        WHERE actual_qty IS NULL
        """,
    )
    return cur.rowcount or 0


def _backfill_pnl_accounted(conn: sqlite3.Connection) -> int:
    """确保存量订单 pnl_accounted 已被置为 0（False）。

    ALTER TABLE ... DEFAULT 0 已覆盖此默认值，这里仅做幂等校验/补齐。
    """
    cur = conn.execute(
        "UPDATE orders SET pnl_accounted = 0 WHERE pnl_accounted IS NULL OR pnl_accounted = ''"
    )
    return cur.rowcount or 0


def main() -> None:
    db_path = _resolve_db_path()
    if not db_path.exists():
        # 数据库文件不存在，说明是全新环境，create_all 会直接建出完整结构，无需迁移
        print(f"[skip] 数据库文件不存在: {db_path}（新环境无需迁移）")
        return

    print(f"[info] 数据库路径: {db_path}")
    # check_same_thread=False 以便与项目其它部分保持一致
    conn = sqlite3.connect(str(db_path))
    try:
        # 检查 orders 表是否存在
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='orders'"
        )
        if cur.fetchone() is None:
            print("[skip] orders 表不存在（新环境，由 create_all 创建）")
            return

        # 1. 添加缺失列
        added_cols = _add_missing_columns(conn)
        if added_cols:
            print(f"[ok] 新增列: {', '.join(added_cols)}")
        else:
            print("[info] 所有目标列已存在，跳过 ALTER TABLE")

        # 2. 创建复合索引
        if _create_index(conn):
            print(f"[ok] 创建索引: {_INDEX_NAME}")
        else:
            print(f"[info] 索引已存在: {_INDEX_NAME}")

        # 3. 回填存量数据
        n_accounted = _backfill_pnl_accounted(conn)
        print(f"[ok] pnl_accounted 回填行数: {n_accounted}")
        n_qty = _backfill_actual_qty(conn)
        print(f"[ok] actual_qty 回填行数: {n_qty}")

        conn.commit()
        print("[done] 迁移完成")
    except Exception as exc:
        conn.rollback()
        print(f"[error] 迁移失败: {exc}", file=sys.stderr)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
