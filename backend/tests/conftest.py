"""pytest 全局配置。

将 tests/ 与 backend/ 根目录加入 sys.path，使：
- legacy 测试可用 `from test_config import ...`（test_config.py 位于 tests/）
- 所有测试可用 `from dsl.xxx import ...` / `from services.xxx import ...`
"""
import os
import sys

_backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_tests_dir = os.path.dirname(os.path.abspath(__file__))

for _p in (_backend_root, _tests_dir):
    if _p not in sys.path:
        sys.path.insert(0, _p)
