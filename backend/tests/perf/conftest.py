"""性能测试目录的 pytest 配置。

- 注册 ``perf`` marker，避免 pytest 警告
- 确保 backend 根目录在 sys.path 中（独立运行时也能导入 backend 模块）
"""
import os
import sys

_backend_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _backend_root not in sys.path:
    sys.path.insert(0, _backend_root)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "perf: 性能基准测试标记，可通过 -m 'not perf' 在 CI 中选择性跳过",
    )
