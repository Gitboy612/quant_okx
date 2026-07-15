"""模拟盘 E2E 测试统一入口。

用法：
    # 执行全部 E2E 测试
    python run_e2e_tests.py

    # 执行单个模块测试
    python run_e2e_tests.py --module grid
    python run_e2e_tests.py --module trend
    python run_e2e_tests.py --module pnl
    python run_e2e_tests.py --module websocket
    python run_e2e_tests.py --module recovery
    python run_e2e_tests.py --module isolation

    # 执行并生成 JSON 测试报告（输出到 backend/tests/reports/）
    python run_e2e_tests.py --report

    # 组合使用
    python run_e2e_tests.py --module grid --report

设计要点：
1. 基于 pytest.main() 调用，自定义插件捕获每个用例结果
2. --module 参数映射到 e2e/ 目录下对应的测试文件
3. --report 生成 JSON 报告：通过率 / 失败项 / 耗时 / 详情
4. 不依赖第三方 pytest 插件（如 pytest-json-report），使用内置 hook 自实现
5. 报告文件输出到 backend/tests/reports/e2e_report_<timestamp>.json
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

# ---- sys.path 注入（参考 conftest.py 风格）----
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_ROOT = os.path.dirname(_TESTS_DIR)
for _p in (_BACKEND_ROOT, _TESTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest

# ---- 模块映射 ----
# --module 参数值 → e2e 目录下测试文件名（不含路径前缀）
MODULE_MAP = {
    "grid": "test_demo_grid_e2e.py",
    "trend": "test_demo_trend_e2e.py",
    "pnl": "test_demo_pnl_consistency.py",
    "websocket": "test_demo_websocket.py",
    "recovery": "test_demo_recovery.py",
    "isolation": "test_demo_multi_strategy_isolation.py",
}

E2E_DIR = os.path.join(_TESTS_DIR, "e2e")
REPORTS_DIR = os.path.join(_TESTS_DIR, "reports")


# ============================================================
# 自定义 pytest 插件：捕获每个测试用例结果
# ============================================================


class E2EReportPlugin:
    """捕获 pytest 运行结果，生成结构化报告数据。

    实现的 hook：
    - pytest_runtest_logreport: 每个测试阶段（setup/call/teardown）的结果
    - pytest_sessionfinish: 会话结束时间戳
    - pytest_terminal_summary: 控制台追加自定义摘要
    """

    def __init__(self):
        self.results = []  # 每个用例的最终结果
        self._seen = {}  # nodeid → 已记录的阶段，避免重复
        self.session_start = None
        self.session_end = None

    def pytest_sessionstart(self, session):
        self.session_start = time.time()

    def pytest_sessionfinish(self, session, exitstatus):
        self.session_end = time.time()

    def pytest_runtest_logreport(self, report):
        # 只关心 call 阶段（实际测试执行）；setup/teardown 失败也算失败
        nodeid = report.nodeid
        if report.when == "call":
            # 正常 call 阶段结果
            self._record(nodeid, report)
        elif report.when in ("setup", "teardown") and report.failed:
            # setup/teardown 阶段失败（如 fixture 异常），标记为 error
            self._record(nodeid, report, is_error=True)

    def _record(self, nodeid, report, is_error=False):
        # 同一 nodeid 只记录一次最终结果（call 优先于 setup/teardown error）
        if nodeid in self._seen and not is_error:
            return
        if is_error and nodeid in self._seen:
            return

        # 解析模块名与测试名
        # nodeid 格式: e2e/test_demo_grid_e2e.py::test_grid_create_template
        parts = nodeid.split("::")
        test_name = parts[-1] if parts else nodeid
        module_file = parts[0] if parts else ""
        module_name = os.path.basename(module_file).replace(".py", "")

        outcome = "error" if is_error else report.outcome  # passed/failed/skipped

        # 提取失败信息
        message = ""
        if outcome in ("failed", "error"):
            if report.longrepr:
                try:
                    # longrepr 可能是字符串或对象
                    message = str(report.longrepr)
                    # 截断过长的错误信息
                    if len(message) > 2000:
                        message = message[:2000] + "...(truncated)"
                except Exception:
                    message = "<unable to extract failure message>"

        self.results.append({
            "module": module_name,
            "test": test_name,
            "nodeid": nodeid,
            "outcome": outcome,
            "duration": round(report.duration, 3),
            "message": message,
        })
        self._seen[nodeid] = True

    def build_report(self, module_filter):
        """生成 JSON 报告字典。"""
        total = len(self.results)
        passed = sum(1 for r in self.results if r["outcome"] == "passed")
        failed = sum(1 for r in self.results if r["outcome"] == "failed")
        errors = sum(1 for r in self.results if r["outcome"] == "error")
        skipped = sum(1 for r in self.results if r["outcome"] == "skipped")

        duration = 0.0
        if self.session_start and self.session_end:
            duration = round(self.session_end - self.session_start, 2)

        pass_rate = round(passed / total, 4) if total > 0 else 0.0

        failures = [
            {
                "module": r["module"],
                "test": r["test"],
                "outcome": r["outcome"],
                "duration": r["duration"],
                "message": r["message"],
            }
            for r in self.results
            if r["outcome"] in ("failed", "error")
        ]

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "module": module_filter,
            "total": total,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "skipped": skipped,
            "pass_rate": pass_rate,
            "duration_seconds": duration,
            "failures": failures,
            "summary": f"{passed}/{total} passed ({pass_rate * 100:.2f}%)"
            + (f", {skipped} skipped" if skipped else "")
            + (f", {errors} errors" if errors else ""),
        }

    def pytest_terminal_summary(self, terminalreporter, exitstatus, config):
        """在 pytest 控制台输出后追加 E2E 摘要。"""
        terminal_report = self.build_report(None)
        terminalreporter.write_line("")
        terminalreporter.write_line(
            f"E2E 汇总: {terminal_report['summary']}  耗时 {terminal_report['duration_seconds']}s",
            green=terminal_report["failed"] == 0 and terminal_report["errors"] == 0,
            bold=True,
        )


# ============================================================
# 报告文件写入
# ============================================================


def _write_report(report_data, reports_dir):
    """将报告写入 JSON 文件，返回文件路径。"""
    os.makedirs(reports_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    module_tag = report_data.get("module") or "all"
    filename = f"e2e_report_{module_tag}_{ts}.json"
    filepath = os.path.join(reports_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)
    return filepath


# ============================================================
# 主入口
# ============================================================


def _resolve_module_targets(module_filter):
    """将 --module 参数解析为 pytest 目标路径列表。"""
    if not module_filter or module_filter == "all":
        return [E2E_DIR]
    if module_filter not in MODULE_MAP:
        raise ValueError(
            f"未知模块 '{module_filter}'，可选值: all, {', '.join(MODULE_MAP.keys())}"
        )
    return [os.path.join(E2E_DIR, MODULE_MAP[module_filter])]


def _build_pytest_args(targets):
    """构建 pytest.main() 参数列表。"""
    args = [
        "-v",
        "--tb=short",
        "-p", "no:cacheprovider",  # 禁用缓存，避免跨运行状态污染
        "-m", "not demo",  # 默认跳过需真实 API 的 @pytest.mark.demo 测试
    ]
    args.extend(targets)
    return args


def run_e2e(module_filter=None, generate_report=False):
    """执行 E2E 测试。

    Args:
        module_filter: 模块名（grid/trend/pnl/websocket/recovery/isolation）或 None/all
        generate_report: 是否生成 JSON 报告文件

    Returns:
        (exit_code, report_data)
    """
    targets = _resolve_module_targets(module_filter)
    pytest_args = _build_pytest_args(targets)

    plugin = E2EReportPlugin()

    print("=" * 60)
    print("  模拟盘 E2E 测试套件")
    print(f"  模块: {module_filter or 'all'}")
    print(f"  目标: {targets}")
    print("=" * 60)

    exit_code = pytest.main(pytest_args, plugins=[plugin])

    report_data = plugin.build_report(module_filter)

    print("\n" + "=" * 60)
    print("  E2E 测试报告")
    print("=" * 60)
    print(f"  总数: {report_data['total']}")
    print(f"  通过: {report_data['passed']}")
    print(f"  失败: {report_data['failed']}")
    print(f"  错误: {report_data['errors']}")
    print(f"  跳过: {report_data['skipped']}")
    print(f"  通过率: {report_data['pass_rate'] * 100:.2f}%")
    print(f"  耗时: {report_data['duration_seconds']}s")
    print(f"  摘要: {report_data['summary']}")

    if report_data["failures"]:
        print("\n失败/错误详情:")
        for f in report_data["failures"]:
            print(f"  [{f['module']}] {f['test']} ({f['outcome']}, {f['duration']}s)")
            if f["message"]:
                # 仅打印首行摘要
                first_line = f["message"].split("\n")[0][:200]
                print(f"    → {first_line}")

    if generate_report:
        filepath = _write_report(report_data, REPORTS_DIR)
        print(f"\n报告已生成: {filepath}")
    else:
        print("\n(使用 --report 参数可生成 JSON 报告文件)")

    return exit_code, report_data


def main():
    parser = argparse.ArgumentParser(
        description="模拟盘 E2E 测试统一入口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python run_e2e_tests.py                      # 执行全部 E2E 测试
  python run_e2e_tests.py --module grid         # 仅执行网格策略测试
  python run_e2e_tests.py --report              # 执行并生成 JSON 报告
  python run_e2e_tests.py --module pnl --report # 执行 PnL 测试并生成报告
        """,
    )
    parser.add_argument(
        "--module",
        choices=["all"] + list(MODULE_MAP.keys()),
        default="all",
        help="指定测试模块 (默认: all)",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="生成 JSON 测试报告到 backend/tests/reports/ 目录",
    )
    args = parser.parse_args()

    exit_code, _ = run_e2e(
        module_filter=args.module if args.module != "all" else None,
        generate_report=args.report,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
