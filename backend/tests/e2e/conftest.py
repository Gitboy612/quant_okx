"""E2E 测试 conftest —— 从 conftest_e2e 导入所有 fixture。

pytest 自动加载本文件，使 conftest_e2e 中定义的 fixture 对 e2e 下所有测试可用。
"""
import os
import sys

# 确保 e2e 目录在 sys.path 中，使 conftest_e2e 可被导入
_E2E_DIR = os.path.dirname(os.path.abspath(__file__))
_TESTS_DIR = os.path.dirname(_E2E_DIR)
_BACKEND_ROOT = os.path.dirname(_TESTS_DIR)
for _p in (_BACKEND_ROOT, _TESTS_DIR, _E2E_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from conftest_e2e import (  # noqa: F401,E402
    demo_account_id,
    test_client,
    cleanup_strategy,
    mock_okx,
    _init_db_session,
    _isolate_engine_state,
    DEMO_ACCOUNT_ID,
    SKIP_REASON,
    get_builtin_template_id,
    wait_for,
    count_live_orders,
    get_instance_status,
    get_latest_pnl,
)
