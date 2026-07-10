"""launcher 事件循环策略测试（Task 1.3）。

验证 Windows 平台导入 launcher 时事件循环策略被主动设置为
``WindowsProactorEventLoopPolicy``，避免 SelectorEventLoop 的 512 句柄上限
导致 "too many file descriptors" 错误。

测试通过 ``monkeypatch`` 将 ``sys.platform`` 置为 ``"win32"``，并预先把策略
切到非 Proactor（``WindowsSelectorEventLoopPolicy``），再用 ``importlib.reload``
重新执行 launcher 模块顶层代码，断言策略被切换为 Proactor。
"""
import sys
import os
import asyncio
import importlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

# Windows 专属事件循环策略类仅在 win32 平台存在
pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="Windows 专属事件循环策略测试",
)


def test_launcher_sets_proactor_policy_on_windows(monkeypatch):
    """Windows 平台导入 launcher 后策略为 WindowsProactorEventLoopPolicy。"""
    original_policy = asyncio.get_event_loop_policy()
    try:
        # 前置：切到非 Proactor 策略，证明后续切换由 launcher 代码完成
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        assert not isinstance(
            asyncio.get_event_loop_policy(), asyncio.WindowsProactorEventLoopPolicy
        )

        monkeypatch.setattr(sys, "platform", "win32")
        import launcher
        importlib.reload(launcher)

        policy = asyncio.get_event_loop_policy()
        assert isinstance(policy, asyncio.WindowsProactorEventLoopPolicy)
    finally:
        asyncio.set_event_loop_policy(original_policy)


def test_launcher_does_not_force_proactor_on_non_windows(monkeypatch):
    """非 Windows 平台导入 launcher 不应强制覆盖现有策略。"""
    original_policy = asyncio.get_event_loop_policy()
    try:
        # 选一个非 Proactor 策略作为前置状态
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        before = asyncio.get_event_loop_policy()

        monkeypatch.setattr(sys, "platform", "linux")
        import launcher
        importlib.reload(launcher)

        # 非 win32 分支不调用 set_event_loop_policy，策略保持不变
        assert asyncio.get_event_loop_policy() is before
    finally:
        asyncio.set_event_loop_policy(original_policy)
