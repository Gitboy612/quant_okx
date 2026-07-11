"""每日回归测试脚本。

自动化执行 E2E 测试套件的全流程：
1. 启动后端服务（uvicorn backend.main:app）
2. 等待服务就绪（最多 30s）
3. 运行 E2E 测试套件（调用 run_e2e_tests.run_e2e）
4. 生成测试报告（JSON + HTML 格式）
5. 关闭后端服务
6. 测试失败时可选发送通知（--notify 参数）

用法：
    python scripts/daily_regression.py                     # 默认执行全部 E2E 测试
    python scripts/daily_regression.py --module grid        # 仅测试 grid 模块
    python scripts/daily_regression.py --notify             # 失败时发送通知
    python scripts/daily_regression.py --host 127.0.0.1 --port 8000  # 自定义地址
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

# ---- 路径注入 ----
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
_BACKEND_ROOT = _PROJECT_ROOT / "backend"
_TESTS_DIR = _BACKEND_ROOT / "tests"
for _p in (str(_PROJECT_ROOT), str(_BACKEND_ROOT), str(_TESTS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from config import HOST as DEFAULT_HOST, PORT as DEFAULT_PORT  # noqa: E402

REPORTS_DIR = _TESTS_DIR / "reports"
DEFAULT_DURATION_LOG = _PROJECT_ROOT / "scripts" / "daily_regression.log"


# ============================================================
# 后端服务管理
# ============================================================


def _build_uvicorn_command(host: str, port: int) -> list[str]:
    """构建启动 uvicorn 的命令（以子进程方式运行）。"""
    return [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.main:app",
        "--host",
        host,
        "--port",
        str(port),
    ]


def _wait_for_service(host: str, port: int, timeout: float = 30.0) -> bool:
    """轮询健康检查端点，等待服务就绪。

    通过请求 /docs 页面判断服务是否已启动（FastAPI 默认提供）。
    返回 True 表示服务就绪，False 表示超时。
    """
    url = f"http://{host}:{port}/docs"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = httpx.get(url, timeout=3.0, follow_redirects=True)
            if 200 <= resp.status_code < 500:
                return True
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout):
            pass
        time.sleep(1.0)
    return False


def _terminate_process(proc: subprocess.Popen) -> None:
    """安全终止子进程：先 SIGTERM，超时后 SIGKILL。"""
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            # Windows 下发送 CTRL_BREAK_EVENT 终止进程树
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            proc.terminate()
    except (ProcessLookupError, OSError):
        return
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


# ============================================================
# 通知
# ============================================================


async def _send_failure_notification(report_data: dict, module: str | None) -> int:
    """测试失败时发送通知，调用 NotificationService。

    返回成功发送的渠道数（0 表示未发送或无匹配规则）。
    通知失败不影响主流程。
    """
    try:
        from services.notification_service import notification_service
    except Exception as e:
        print(f"[notify] 导入 NotificationService 失败: {e}")
        return 0

    total = report_data.get("total", 0)
    passed = report_data.get("passed", 0)
    failed = report_data.get("failed", 0)
    errors = report_data.get("errors", 0)
    pass_rate = report_data.get("pass_rate", 0.0)

    title = f"[每日回归] E2E 测试失败告警 ({failed + errors} 项失败)"
    message = (
        f"模块: {module or 'all'}\n"
        f"通过率: {pass_rate * 100:.2f}% ({passed}/{total})\n"
        f"失败: {failed}, 错误: {errors}\n"
        f"耗时: {report_data.get('duration_seconds', 0)}s\n"
        f"时间: {report_data.get('generated_at', '')}"
    )

    failures_summary = []
    for f in report_data.get("failures", [])[:10]:
        failures_summary.append(
            f"[{f['module']}] {f['test']} ({f['outcome']}): "
            f"{f.get('message', '').splitlines()[0][:150] if f.get('message') else ''}"
        )

    details = {
        "module": module or "all",
        "total": total,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "pass_rate": pass_rate,
        "failures": failures_summary,
        "report_type": "daily_regression",
    }

    try:
        count = await notification_service.notify(
            event_type="test_failure",
            title=title,
            message=message,
            details=details,
        )
        print(f"[notify] 通知已发送到 {count} 个渠道")
        return count
    except Exception as e:
        print(f"[notify] 发送通知异常: {e}")
        return 0


# ============================================================
# 报告写入
# ============================================================


def _write_daily_report(report_data: dict, module: str | None) -> tuple[str, str]:
    """将报告写入 JSON 文件，并生成 HTML 文件。

    返回 (json_path, html_path)。
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    module_tag = module or "all"
    json_filename = f"daily_regression_{ts}.json"
    html_filename = f"daily_regression_{ts}.html"

    json_path = REPORTS_DIR / json_filename
    html_path = REPORTS_DIR / html_filename

    # 注入回归测试专属字段
    payload = dict(report_data)
    payload["report_type"] = "daily_regression"
    payload["module"] = module_tag
    payload["generated_at_local"] = datetime.now().isoformat()

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # 生成 HTML（调用 generate_report 模块）
    try:
        from generate_report import generate_html_report

        generate_html_report(payload, str(html_path))
    except Exception as e:
        print(f"[report] HTML 报告生成失败（仅保留 JSON）: {e}")
        # 兜底：写入最简 HTML
        _write_fallback_html(payload, str(html_path))

    return str(json_path), str(html_path)


def _write_fallback_html(report_data: dict, html_path: str) -> None:
    """当 generate_report 模块不可用时的兜底 HTML。"""
    total = report_data.get("total", 0)
    passed = report_data.get("passed", 0)
    failed = report_data.get("failed", 0)
    pass_rate = report_data.get("pass_rate", 0.0)
    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>每日回归报告</title></head>
<body>
<h1>每日回归测试报告</h1>
<p>生成时间: {report_data.get('generated_at', '')}</p>
<p>总数: {total} | 通过: {passed} | 失败: {failed} | 通过率: {pass_rate * 100:.2f}%</p>
</body></html>"""
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)


# ============================================================
# 主流程
# ============================================================


async def run_regression(
    module: str | None = None,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    notify: bool = False,
    skip_server_start: bool = False,
) -> dict:
    """执行每日回归测试完整流程。

    Args:
        module: 测试模块名（None 表示全部）
        host: 后端服务地址
        port: 后端服务端口
        notify: 失败时是否发送通知
        skip_server_start: 跳过启动后端（用于服务已运行时）

    Returns:
        包含 report_data / json_path / html_path / exit_code 的字典
    """
    print("=" * 60)
    print("  每日回归测试")
    print(f"  模块: {module or 'all'}")
    print(f"  服务: http://{host}:{port}")
    print(f"  通知: {'开启' if notify else '关闭'}")
    print("=" * 60)

    proc: subprocess.Popen | None = None

    # 1. 启动后端服务
    if not skip_server_start:
        print("\n[1/5] 启动后端服务...")
        env = os.environ.copy()
        # 确保 cwd 为项目根目录，使 backend.main 可被导入
        env["PYTHONPATH"] = str(_PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        cmd = _build_uvicorn_command(host, port)
        try:
            if os.name == "nt":
                # Windows 下使用 CREATE_NEW_PROCESS_GROUP 以支持 CTRL_BREAK_EVENT
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(_PROJECT_ROOT),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                )
            else:
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(_PROJECT_ROOT),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    preexec_fn=os.setsid,
                )
        except Exception as e:
            print(f"[error] 启动后端服务失败: {e}")
            return {"exit_code": 1, "error": f"启动后端失败: {e}"}
    else:
        print("\n[1/5] 跳过后端启动（--skip-server-start）")

    # 2. 等待服务就绪
    print("\n[2/5] 等待服务就绪（最多 30s）...")
    ready = _wait_for_service(host, port, timeout=30.0)
    if not ready:
        print("[error] 后端服务 30s 内未就绪")
        if proc is not None:
            _terminate_process(proc)
        return {"exit_code": 1, "error": "后端服务就绪超时"}
    print("[ok] 后端服务已就绪")

    # 3. 运行 E2E 测试套件
    print("\n[3/5] 运行 E2E 测试套件...")
    try:
        from run_e2e_tests import run_e2e

        exit_code, report_data = run_e2e(
            module_filter=module,
            generate_report=False,  # 由本脚本统一写报告
        )
    except Exception as e:
        print(f"[error] E2E 测试执行异常: {e}")
        report_data = {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "errors": 1,
            "skipped": 0,
            "pass_rate": 0.0,
            "duration_seconds": 0.0,
            "failures": [],
            "summary": f"执行异常: {e}",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "module": module or "all",
        }
        exit_code = 1

    # 4. 生成报告
    print("\n[4/5] 生成测试报告...")
    json_path, html_path = _write_daily_report(report_data, module)
    print(f"[ok] JSON 报告: {json_path}")
    print(f"[ok] HTML 报告: {html_path}")

    # 5. 关闭后端服务
    if proc is not None:
        print("\n[5/5] 关闭后端服务...")
        _terminate_process(proc)
        print("[ok] 后端服务已关闭")
    else:
        print("\n[5/5] 跳过后端关闭（外部服务）")

    # 通知
    has_failure = report_data.get("failed", 0) > 0 or report_data.get("errors", 0) > 0
    if notify and has_failure:
        print("\n[notify] 发送失败通知...")
        await _send_failure_notification(report_data, module)

    # 控制台汇总
    print("\n" + "=" * 60)
    print("  每日回归测试完成")
    print(f"  摘要: {report_data.get('summary', '')}")
    print(f"  通过率: {report_data.get('pass_rate', 0) * 100:.2f}%")
    print(f"  耗时: {report_data.get('duration_seconds', 0)}s")
    print(f"  报告: {json_path}")
    print("=" * 60)

    return {
        "exit_code": exit_code,
        "report_data": report_data,
        "json_path": json_path,
        "html_path": html_path,
    }


def main():
    parser = argparse.ArgumentParser(
        description="每日回归测试脚本：启动后端 → 运行 E2E → 生成报告 → 关闭后端",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/daily_regression.py                      # 执行全部 E2E 测试
  python scripts/daily_regression.py --module grid        # 仅测试 grid 模块
  python scripts/daily_regression.py --notify             # 失败时发送通知
  python scripts/daily_regression.py --skip-server-start  # 服务已运行时
        """,
    )
    parser.add_argument(
        "--module",
        default="all",
        help="测试模块 (all/grid/trend/pnl/websocket/recovery)，默认 all",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"后端服务地址，默认 {DEFAULT_HOST}",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"后端服务端口，默认 {DEFAULT_PORT}",
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="测试失败时发送通知（调用 NotificationService）",
    )
    parser.add_argument(
        "--skip-server-start",
        action="store_true",
        help="跳过启动后端服务（用于服务已运行的场景）",
    )
    args = parser.parse_args()

    module = args.module if args.module != "all" else None

    result = asyncio.run(
        run_regression(
            module=module,
            host=args.host,
            port=args.port,
            notify=args.notify,
            skip_server_start=args.skip_server_start,
        )
    )

    sys.exit(result.get("exit_code", 1))


if __name__ == "__main__":
    main()
