"""一次性迁移脚本：清理 pnl_records 历史异常数据。

异常判定：``ABS(unrealized_pnl) > 1000`` 且 ``avg_buy_price`` 为 0 或 NULL。
这类记录通常源于建仓前误触发的盈亏快照（avg_buy_price=0 却计算出极大浮亏），
修正方式为将 ``unrealized_pnl`` 置 0，并以已实现盈亏回填 ``total_pnl``。

本脚本可独立运行：

    python backend/migrations/fix_pnl_anomaly_records.py

特性：
    - 幂等：重复运行不会报错；无异常记录时打印"无需修复"
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


# 异常记录查询 SQL
_SELECT_ANOMALY_SQL = """
SELECT id, strategy_instance_id, unrealized_pnl, avg_buy_price, recorded_at
FROM pnl_records
WHERE ABS(unrealized_pnl) > 1000 AND (avg_buy_price = 0 OR avg_buy_price IS NULL)
"""

# 修正单条异常记录 SQL：unrealized_pnl 归零，total_pnl 以 realized_pnl 回填
_FIX_ANOMALY_SQL = (
    "UPDATE pnl_records SET unrealized_pnl = 0, total_pnl = realized_pnl WHERE id = ?"
)


def _fetch_anomalies(conn: sqlite3.Connection) -> list[tuple]:
    """查询所有异常 pnl_records 记录。"""
    cur = conn.execute(_SELECT_ANOMALY_SQL)
    return cur.fetchall()


def _fix_anomaly(conn: sqlite3.Connection, record_id: int) -> int:
    """修正单条异常记录，返回受影响行数。"""
    cur = conn.execute(_FIX_ANOMALY_SQL, (record_id,))
    return cur.rowcount or 0


def main() -> None:
    db_path = _resolve_db_path()
    if not db_path.exists():
        # 数据库文件不存在，说明是全新环境，无历史数据需清理
        print(f"[skip] 数据库文件不存在: {db_path}（新环境无需迁移）")
        return

    print(f"[info] 数据库路径: {db_path}")
    conn = sqlite3.connect(str(db_path))
    try:
        # 检查 pnl_records 表是否存在
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='pnl_records'"
        )
        if cur.fetchone() is None:
            print("[skip] pnl_records 表不存在（新环境，无需清理）")
            return

        anomalies = _fetch_anomalies(conn)
        if not anomalies:
            print("[info] 无需修复：未发现异常 pnl_records 记录")
            return

        print(f"[info] 发现 {len(anomalies)} 条异常记录，开始修正：")
        fixed_count = 0
        for row in anomalies:
            record_id, strategy_instance_id, unrealized_pnl, avg_buy_price, recorded_at = row
            affected = _fix_anomaly(conn, record_id)
            if affected:
                fixed_count += affected
                print(
                    f"  - id={record_id} strategy_instance_id={strategy_instance_id} "
                    f"unrealized_pnl={unrealized_pnl} avg_buy_price={avg_buy_price} "
                    f"recorded_at={recorded_at} -> 已修正"
                )

        conn.commit()
        print(f"[done] 共修正 {fixed_count} 条异常记录")
    except Exception as exc:
        conn.rollback()
        print(f"[error] 清理失败: {exc}", file=sys.stderr)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
