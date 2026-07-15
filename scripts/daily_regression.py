"""每日回归测试脚本（Task 11: 连续回归测试闭环）。

扩展自原 monthly-continuous-improvement 阶段的 daily_regression.py，
新增覆盖 W1-W3 全部能力点、退化检测、趋势图、长期运行配置。

执行流程：
1. 启动后端服务（uvicorn backend.main:app，可跳过）
2. 等待服务就绪（最多 30s）
3. 运行全部后端单元测试（pytest tests/ -m "not demo"）
4. 运行 E2E 测试套件（run_e2e_tests.py 全模块）
5. 计算 W1-W3 能力点 breakdown（资金/杠杆/保证金/对账/冲突/响应/波动/maker/隔离）
6. 拉取 /api/monitoring/health 运行时指标（若服务可用）
7. 退化检测：与前一日报告对比（通过率/能力/耗时）
8. 聚合 7/30 天趋势
9. 严重退化自动追加任务到 tasks.md「## 退化修复任务」
10. 生成 JSON + HTML 报告
11. 关闭后端服务
12. 测试失败时可选发送通知（--notify 参数）

报告输出：backend/tests/reports/daily_regression_YYYYMMDD.json

长期运行：
    # 单次运行（默认）
    python scripts/daily_regression.py --once

    # 常驻每日 02:00 执行（避开交易高峰）
    python scripts/daily_regression.py --continuous

    # 也可用系统 cron / 计划任务调度 --once
    # Linux crontab: 0 2 * * * cd /path/to/quant_okx && python scripts/daily_regression.py --once
    # Windows 任务计划: 每日 02:00 启动 "python scripts\\daily_regression.py --once"
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
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
TASKS_MD_PATH = _PROJECT_ROOT / ".trae" / "specs" / "strategy-fundamentals-overhaul" / "tasks.md"
DEFAULT_DAILY_HOUR = 2  # 常驻模式默认每日 02:00 执行

# ============================================================
# W1-W3 能力点定义（Task 11.1）
# capability -> 测试文件名（仅文件名，便于从 nodeid 中匹配）
# ============================================================
CAPABILITY_DEFS: list[tuple[str, str]] = [
    ("capital_limit", "test_capital_limit.py"),
    ("leverage", "test_leverage.py"),
    ("margin_monitor", "test_margin_monitor.py"),
    ("position_reconcile", "test_position_reconcile.py"),
    ("position_conflict", "test_position_conflict.py"),
    ("grid_responsiveness", "test_grid_responsiveness.py"),
    ("volatility_response", "test_volatility_response.py"),
    ("post_only", "test_post_only.py"),
    ("multi_strategy_isolation", "test_demo_multi_strategy_isolation.py"),
]


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
# 测试执行：单元测试 + E2E + 能力点 breakdown
# ============================================================


def _run_pytest_with_plugin(
    target_paths: list[str],
    mark: str = "not demo",
    cwd: str | None = None,
) -> tuple[int, dict]:
    """以 pytest.main 运行测试，使用 E2EReportPlugin 捕获结果。

    Args:
        target_paths: pytest 目标路径列表（文件/目录）
        mark: -m 表达式
        cwd: 工作目录（默认 backend/，用于加载 pytest.ini）

    Returns:
        (exit_code, report_data)
    """
    # 延迟导入避免在模块加载阶段触发 pytest 初始化
    import pytest
    from run_e2e_tests import E2EReportPlugin

    args = [
        "-v",
        "--tb=short",
        "-p", "no:cacheprovider",
        "-m", mark,
    ]
    args.extend(target_paths)

    plugin = E2EReportPlugin()
    # 切换 cwd 以加载 backend/pytest.ini（含 norecursedirs=tests/e2e）
    prev_cwd = os.getcwd()
    if cwd:
        os.chdir(cwd)
    try:
        exit_code = pytest.main(args, plugins=[plugin])
    finally:
        os.chdir(prev_cwd)

    report = plugin.build_report(None)
    # 保留原始 results 以便后续按文件聚合 capability breakdown
    report["_raw_results"] = plugin.results
    return exit_code, report


def _run_unit_tests() -> tuple[int, dict]:
    """运行全部后端单元测试：pytest tests/ -m "not demo"。"""
    print("\n[3.1] 运行后端单元测试套件（tests/ -m 'not demo'）...")
    return _run_pytest_with_plugin(
        target_paths=["tests/"],
        mark="not demo",
        cwd=str(_BACKEND_ROOT),
    )


def _run_e2e_suite() -> tuple[int, dict]:
    """运行 E2E 测试套件（run_e2e_tests 全模块）。

    直接以 _run_pytest_with_plugin 调用 e2e 目录，以便从 plugin.results
    中获取原始测试结果用于 capability_breakdown 聚合。
    """
    print("\n[3.2] 运行 E2E 测试套件（run_e2e_tests 全模块）...")
    try:
        from run_e2e_tests import E2E_DIR

        return _run_pytest_with_plugin(
            target_paths=[E2E_DIR],
            mark="not demo",
            cwd=str(_BACKEND_ROOT),
        )
    except Exception as e:
        print(f"[error] E2E 测试执行异常: {e}")
        report = {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "errors": 1,
            "skipped": 0,
            "pass_rate": 0.0,
            "duration_seconds": 0.0,
            "failures": [],
            "summary": f"E2E 执行异常: {e}",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "module": "all",
            "_raw_results": [],
        }
        return 1, report


def _build_capability_breakdown(
    unit_report: dict, e2e_report: dict
) -> list[dict]:
    """从单元测试与 E2E 测试结果中聚合每个能力点的通过/失败/耗时。

    对 multi_strategy_isolation（e2e 测试）使用 e2e_report；
    其余使用 unit_report 中匹配 nodeid（按文件名）。
    """
    breakdown: list[dict] = []

    unit_results = unit_report.get("_raw_results", [])
    e2e_results = e2e_report.get("_raw_results", [])

    for capability, filename in CAPABILITY_DEFS:
        if capability == "multi_strategy_isolation":
            results = e2e_results
        else:
            results = unit_results

        matched = [r for r in results if filename in r.get("nodeid", "")]
        passed = sum(1 for r in matched if r["outcome"] == "passed")
        failed = sum(1 for r in matched if r["outcome"] in ("failed", "error"))
        duration = round(sum(r.get("duration", 0) for r in matched), 3)

        breakdown.append({
            "capability": capability,
            "test_file": filename,
            "total": len(matched),
            "passed": passed,
            "failed": failed,
            "duration": duration,
            "status": "pass" if (failed == 0 and passed > 0) else (
                "fail" if failed > 0 else "empty"
            ),
        })

    return breakdown


# ============================================================
# 运行时指标拉取（Task 11.2: /api/monitoring/health）
# ============================================================


def _fetch_runtime_metrics(host: str, port: int) -> dict | str:
    """尝试调用 /api/monitoring/health 获取运行时指标。

    该端点需 account_id 查询参数与鉴权，本脚本不持有用户 token，
    若鉴权失败或服务未运行，统一返回字符串 "unavailable"。

    Returns:
        成功时返回字典 {strategies, alerts, summary}；失败返回 "unavailable"。
    """
    base = f"http://{host}:{port}"
    # 先确认服务存活（/docs 不需鉴权）
    try:
        resp = httpx.get(f"{base}/docs", timeout=3.0, follow_redirects=True)
        if resp.status_code >= 500:
            return "unavailable"
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout):
        return "unavailable"

    # 拉取 health（需要 account_id；无 token 时多半返回 401/422）
    # 用 account_id=1 试探，仅作为运行时指标的尽力而为获取
    try:
        resp = httpx.get(
            f"{base}/api/monitoring/health",
            params={"account_id": 1},
            timeout=5.0,
        )
        if 200 <= resp.status_code < 300:
            data = resp.json()
            return _summarize_runtime_metrics(data)
        return "unavailable"
    except Exception:
        return "unavailable"


def _summarize_runtime_metrics(health_data: dict) -> dict:
    """从 /api/monitoring/health 响应中抽取关键指标做摘要。"""
    strategies = health_data.get("strategies", []) or []
    summary = {
        "strategy_count": len(strategies),
        "alerts": health_data.get("alerts", []) or [],
        "p95_latency_max": None,
        "margin_ratio_max": None,
        "capital_usage_max": None,
        "isolation_mismatch_count": 0,
    }

    p95_max = None
    margin_max = None
    usage_max = None
    mismatch_count = 0

    for s in strategies:
        lat = s.get("latency")
        if isinstance(lat, dict):
            p95 = lat.get("p95")
            if p95 is not None:
                p95_max = p95 if p95_max is None else max(p95_max, p95)

        margin = s.get("margin_ratio")
        if margin is not None:
            margin_max = margin if margin_max is None else max(margin_max, margin)

        cap = s.get("capital") or {}
        usage = cap.get("usage_rate")
        if usage is not None:
            usage_max = usage if usage_max is None else max(usage_max, usage)

        iso = s.get("isolation")
        if isinstance(iso, dict) and not iso.get("matched", True):
            mismatch_count += 1

    summary["p95_latency_max"] = p95_max
    summary["margin_ratio_max"] = margin_max
    summary["capital_usage_max"] = usage_max
    summary["isolation_mismatch_count"] = mismatch_count
    return summary


# ============================================================
# 退化检测（Task 11.3）
# ============================================================


def _find_previous_report(today: datetime) -> Path | None:
    """查找前一日 daily_regression 报告。

    优先匹配 daily_regression_YYYYMMDD.json（新格式）；
    回退到带时间戳的 daily_regression_YYYYMMDD_*.json（旧格式）。
    """
    yesterday = today - timedelta(days=1)
    ymd = yesterday.strftime("%Y%m%d")

    # 新格式优先
    fp = REPORTS_DIR / f"daily_regression_{ymd}.json"
    if fp.exists():
        return fp

    # 回退：同日任意时间戳
    candidates = sorted(REPORTS_DIR.glob(f"daily_regression_{ymd}_*.json"))
    return candidates[-1] if candidates else None


def _detect_regressions(
    current: dict, previous: dict
) -> list[dict]:
    """对比当前与前一日报告，返回退化项列表。

    检测维度：
    - 通过率下降（previous > current，按比率）
    - 某能力从 pass 变 fail
    - 单能力耗时上升 > 50%
    """
    regressions: list[dict] = []

    # 1. 通过率退化
    prev_rate = previous.get("metrics", {}).get("test_summary", {}).get("pass_rate")
    curr_rate = current.get("metrics", {}).get("test_summary", {}).get("pass_rate")
    if prev_rate is not None and curr_rate is not None and prev_rate > curr_rate:
        delta = round(prev_rate - curr_rate, 4)
        severity = "critical" if curr_rate < 1.0 else "warning"
        regressions.append({
            "metric": "pass_rate",
            "previous": prev_rate,
            "current": curr_rate,
            "delta": delta,
            "severity": severity,
            "description": f"通过率从 {prev_rate*100:.2f}% 降至 {curr_rate*100:.2f}%",
        })

    # 2. 能力从 pass 变 fail
    prev_cap = {
        b["capability"]: b for b in previous.get("metrics", {}).get("capability_breakdown", [])
    }
    curr_cap = {
        b["capability"]: b for b in current.get("metrics", {}).get("capability_breakdown", [])
    }
    for cap_name, curr_b in curr_cap.items():
        prev_b = prev_cap.get(cap_name)
        if prev_b is None:
            continue
        if prev_b.get("status") == "pass" and curr_b.get("status") == "fail":
            regressions.append({
                "metric": f"capability:{cap_name}",
                "previous": "pass",
                "current": "fail",
                "delta": "pass->fail",
                "severity": "critical",
                "description": (
                    f"能力点 {cap_name} 从通过退化为失败"
                    f"（{curr_b.get('failed', 0)} 项失败）"
                ),
            })

    # 3. 单能力耗时上升 > 50%
    for cap_name, curr_b in curr_cap.items():
        prev_b = prev_cap.get(cap_name)
        if prev_b is None:
            continue
        prev_dur = prev_b.get("duration", 0) or 0
        curr_dur = curr_b.get("duration", 0) or 0
        if prev_dur > 0 and curr_dur > prev_dur * 1.5:
            delta_pct = round((curr_dur - prev_dur) / prev_dur * 100, 1)
            regressions.append({
                "metric": f"duration:{cap_name}",
                "previous": prev_dur,
                "current": curr_dur,
                "delta": f"+{delta_pct}%",
                "severity": "warning",
                "description": (
                    f"能力点 {cap_name} 耗时从 {prev_dur}s 升至 {curr_dur}s"
                    f"（+{delta_pct}%）"
                ),
            })

    return regressions


def _append_regression_tasks(regressions: list[dict], today: datetime) -> None:
    """严重退化项追加到 tasks.md「## 退化修复任务」section。

    只追加 severity=critical 的退化项；若 section 不存在则创建。
    使用 Edit 工具或文件追加方式，不覆盖现有内容。
    """
    critical = [r for r in regressions if r.get("severity") == "critical"]
    if not critical:
        return

    if not TASKS_MD_PATH.exists():
        print(f"[warn] tasks.md 不存在: {TASKS_MD_PATH}，跳过追加退化修复任务")
        return

    # 读取现有内容
    with open(TASKS_MD_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    date_str = today.strftime("%Y-%m-%d")
    new_lines: list[str] = []
    for r in critical:
        new_lines.append(
            f"- [ ] 修复退化: {r['metric']} {r['description']}（检测于 {date_str}）"
        )

    section_header = "## 退化修复任务"
    if section_header in content:
        # 已有 section：在其末尾追加（找下一个 ## 标题前插入，或直接追加到 section 末尾）
        # 简单做法：定位 section 起始，追加到该 section 内末尾
        idx = content.index(section_header)
        # 找到下一个 ## 标题的位置（同级的下一节）
        after_section = content[idx + len(section_header):]
        # 找下一个 "\n## " 出现的位置
        next_section_match = re.search(r"\n## ", after_section)
        if next_section_match:
            insert_pos = idx + len(section_header) + next_section_match.start()
            new_block = "\n" + "\n".join(new_lines) + "\n"
            content = content[:insert_pos] + new_block + content[insert_pos:]
        else:
            # section 是最后一节，追加到文件末尾
            if not content.endswith("\n"):
                content += "\n"
            content += "\n" + "\n".join(new_lines) + "\n"
    else:
        # section 不存在，创建并追加到文件末尾
        if not content.endswith("\n"):
            content += "\n"
        content += f"\n{section_header}\n\n" + "\n".join(new_lines) + "\n"

    with open(TASKS_MD_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"[regression] 已追加 {len(critical)} 条退化修复任务到 tasks.md")


# ============================================================
# 趋势聚合（Task 11.4: 7/30 天趋势）
# ============================================================


def _load_recent_daily_reports(days: int) -> list[dict]:
    """加载最近 N 天的 daily_regression_*.json 报告，按日期正序返回。

    兼容新格式 daily_regression_YYYYMMDD.json 与旧格式 _YYYYMMDD_HHMMSS.json。
    """
    if not REPORTS_DIR.exists():
        return []

    candidates: list[tuple[float, dict]] = []
    now_ts = datetime.now(timezone.utc).timestamp()
    cutoff = now_ts - days * 86400

    for pattern in ("daily_regression_*.json",):
        for fp in REPORTS_DIR.glob(pattern):
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

            ts_str = data.get("generated_at") or data.get("generated_at_local", "")
            try:
                normalized = ts_str.replace("Z", "+00:00") if ts_str else ""
                dt = datetime.fromisoformat(normalized)
                ts = dt.timestamp()
            except (ValueError, TypeError):
                ts = fp.stat().st_mtime

            if ts < cutoff:
                continue
            data["_sort_ts"] = ts
            candidates.append((ts, data))

    candidates.sort(key=lambda x: x[0])
    return [d for _, d in candidates]


def _build_trend_data() -> dict:
    """聚合最近 7/30 天报告，生成趋势数据。"""
    reports_7 = _load_recent_daily_reports(days=7)
    reports_30 = _load_recent_daily_reports(days=30)

    def _points(reports: list[dict]) -> list[dict]:
        points: list[dict] = []
        for r in reports:
            ts = r.get("_sort_ts")
            if ts is None:
                continue
            try:
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                date_label = dt.strftime("%Y-%m-%d")
            except (OSError, ValueError):
                date_label = "?"

            test_summary = r.get("metrics", {}).get("test_summary", {})
            pass_rate = test_summary.get("pass_rate", r.get("pass_rate", 0.0))
            total = test_summary.get("total", r.get("total", 0))
            passed = test_summary.get("passed", r.get("passed", 0))

            # 各能力通过数快照
            cap_snapshot = {
                b["capability"]: {
                    "passed": b.get("passed", 0),
                    "failed": b.get("failed", 0),
                    "status": b.get("status", "unknown"),
                }
                for b in r.get("metrics", {}).get("capability_breakdown", [])
            }

            points.append({
                "date": date_label,
                "pass_rate": round(float(pass_rate), 4),
                "total": total,
                "passed": passed,
                "capabilities": cap_snapshot,
            })
        return points

    return {
        "days_7": _points(reports_7),
        "days_30": _points(reports_30),
    }


def _render_ascii_trend(trend: dict) -> str:
    """生成简单 ASCII 趋势图（便于控制台与文本场景消费）。"""
    points = trend.get("days_7", [])
    if not points:
        return "(暂无历史数据)"

    lines = ["近 7 天通过率趋势（每格=10%）:"]
    for p in points:
        rate = p["pass_rate"]
        # 用 █ 表示 10% 一格，最多 10 格
        filled = int(rate * 10)
        bar = "█" * filled + "░" * (10 - filled)
        lines.append(f"  {p['date']}  {bar}  {rate*100:5.1f}%  ({p['passed']}/{p['total']})")
    return "\n".join(lines)


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

    test_summary = report_data.get("metrics", {}).get("test_summary", {})
    total = test_summary.get("total", report_data.get("total", 0))
    passed = test_summary.get("passed", report_data.get("passed", 0))
    failed = test_summary.get("failed", report_data.get("failed", 0))
    pass_rate = test_summary.get("pass_rate", report_data.get("pass_rate", 0.0))
    duration = test_summary.get("duration", report_data.get("duration_seconds", 0))

    title = f"[每日回归] 测试失败告警 ({failed} 项失败)"
    message = (
        f"模块: {module or 'all'}\n"
        f"通过率: {pass_rate * 100:.2f}% ({passed}/{total})\n"
        f"失败: {failed}\n"
        f"耗时: {duration}s\n"
        f"时间: {report_data.get('generated_at', '')}"
    )

    # 退化项摘要
    regressions = report_data.get("regressions", [])
    reg_summary = []
    for r in regressions[:5]:
        reg_summary.append(f"  - [{r.get('severity')}] {r.get('description', '')}")

    details = {
        "module": module or "all",
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": pass_rate,
        "regressions": regressions,
        "report_type": "daily_regression",
    }

    try:
        count = await notification_service.notify(
            event_type="test_failure",
            title=title,
            message=message + ("\n退化项:\n" + "\n".join(reg_summary) if reg_summary else ""),
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

    文件名格式：daily_regression_YYYYMMDD.json / .html
    （同日重跑会覆盖；前一日查找通过 _find_previous_report 兼容旧格式）

    返回 (json_path, html_path)。
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now()
    ymd = today.strftime("%Y%m%d")

    json_filename = f"daily_regression_{ymd}.json"
    html_filename = f"daily_regression_{ymd}.html"

    json_path = REPORTS_DIR / json_filename
    html_path = REPORTS_DIR / html_filename

    # 注入回归测试专属字段
    payload = dict(report_data)
    payload["report_type"] = "daily_regression"
    payload["module"] = module or "all"
    payload["generated_at_local"] = today.isoformat()

    # 移除内部辅助字段（避免污染 JSON）
    payload.pop("_raw_results", None)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # 生成 HTML（优先调用 generate_report 模块；失败回退到内置实现）
    try:
        from generate_report import generate_html_report

        generate_html_report(payload, str(html_path))
        # 追加 capability_breakdown / regressions 段落（generate_report 不感知这些字段）
        _append_capability_html(str(html_path), payload)
    except Exception as e:
        print(f"[report] HTML 报告生成失败（仅保留 JSON）: {e}")
        _write_fallback_html(payload, str(html_path))

    return str(json_path), str(html_path)


def _append_capability_html(html_path: str, payload: dict) -> None:
    """在已生成的 HTML 报告中追加能力点 breakdown 与退化项段落。

    简单实现：在 </body> 之前插入两段 HTML。
    """
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()
    except OSError:
        return

    metrics = payload.get("metrics", {}) or {}
    breakdown = metrics.get("capability_breakdown", []) or []
    regressions = payload.get("regressions", []) or []

    parts: list[str] = []

    # 能力点 breakdown 段落
    if breakdown:
        rows = []
        for b in breakdown:
            status = b.get("status", "unknown")
            color = {
                "pass": "#16a34a",
                "fail": "#dc2626",
                "empty": "#9ca3af",
            }.get(status, "#6b7280")
            rows.append(
                f"<tr>"
                f"<td>{b['capability']}</td>"
                f"<td><code>{b['test_file']}</code></td>"
                f"<td style='text-align:center'>{b['passed']}</td>"
                f"<td style='text-align:center'>{b['failed']}</td>"
                f"<td style='text-align:center'>{b['duration']}s</td>"
                f"<td style='text-align:center;color:{color};font-weight:600'>"
                f"{status}</td>"
                f"</tr>"
            )
        parts.append(
            '<div class="section">'
            '<h2>能力点 Breakdown（W1-W3）</h2>'
            '<table style="width:100%;border-collapse:collapse;font-size:13px;">'
            '<thead><tr style="background:#f3f4f6;">'
            '<th style="text-align:left;padding:8px;">能力</th>'
            '<th style="text-align:left;padding:8px;">测试文件</th>'
            '<th style="padding:8px;">通过</th>'
            '<th style="padding:8px;">失败</th>'
            '<th style="padding:8px;">耗时</th>'
            '<th style="padding:8px;">状态</th>'
            '</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody>'
            '</table>'
            '</div>'
        )

    # 退化项段落
    if regressions:
        items = []
        for r in regressions:
            sev = r.get("severity", "warning")
            sev_color = "#dc2626" if sev == "critical" else "#f59e0b"
            items.append(
                f'<div class="failure-item" style="border-color:#fef3c7;background:#fffbeb;">'
                f'<div class="ftitle" style="color:{sev_color};">'
                f'[{sev}] {r.get("metric", "")}</div>'
                f'<div class="fmeta">前值: {r.get("previous")} → 当前: {r.get("current")} '
                f'({r.get("delta")})</div>'
                f'<pre style="white-space:pre-wrap;">{r.get("description", "")}</pre>'
                f'</div>'
            )
        parts.append(
            '<div class="section">'
            '<h2>退化项（对比前一日）</h2>'
            f'{"".join(items)}'
            '</div>'
        )
    else:
        parts.append(
            '<div class="section">'
            '<h2>退化项（对比前一日）</h2>'
            '<div class="no-failure">✅ 无退化项</div>'
            '</div>'
        )

    # 运行时指标段落
    runtime = metrics.get("runtime_metrics")
    if isinstance(runtime, dict):
        rt_lines = []
        rt_lines.append(f"<p><b>策略数:</b> {runtime.get('strategy_count', 0)}</p>")
        rt_lines.append(
            f"<p><b>最大 P95 延迟:</b> "
            f"{runtime.get('p95_latency_max') if runtime.get('p95_latency_max') is not None else 'N/A'} s</p>"
        )
        rt_lines.append(
            f"<p><b>最大保证金占用率:</b> "
            f"{(runtime.get('margin_ratio_max')*100 if runtime.get('margin_ratio_max') is not None else 'N/A')}%</p>"
        )
        rt_lines.append(
            f"<p><b>最大资金使用率:</b> "
            f"{(runtime.get('capital_usage_max')*100 if runtime.get('capital_usage_max') is not None else 'N/A')}%</p>"
        )
        rt_lines.append(
            f"<p><b>仓位隔离不一致数:</b> "
            f"{runtime.get('isolation_mismatch_count', 0)}</p>"
        )
        alerts = runtime.get("alerts", []) or []
        if alerts:
            alert_items = "".join(
                f'<li style="color:#dc2626;">[{a.get("level")}] {a.get("message", "")}</li>'
                for a in alerts[:10]
            )
            rt_lines.append(f"<p><b>告警 ({len(alerts)}):</b></p><ul>{alert_items}</ul>")
        parts.append(
            '<div class="section">'
            '<h2>运行时指标（/api/monitoring/health）</h2>'
            + "".join(rt_lines)
            + '</div>'
        )

    # 趋势段落（ASCII 风格的简单文本预览）
    trend = payload.get("trend", {}) or {}
    ascii_trend = payload.get("trend_ascii", "")
    if ascii_trend:
        # HTML 中用 <pre> 渲染 ASCII 趋势
        parts.append(
            '<div class="section">'
            '<h2>近 7 天通过率趋势</h2>'
            f'<pre style="font-family:Consolas,Monaco,monospace;font-size:12px;'
            f'background:#fafafa;padding:12px;border-radius:6px;overflow-x:auto;">'
            f'{ascii_trend}</pre>'
            f'<p style="font-size:12px;color:#9ca3af;margin-top:8px;">'
            f'7 天报告数: {len(trend.get("days_7", []))} · '
            f'30 天报告数: {len(trend.get("days_30", []))}'
            '</p>'
            '</div>'
        )

    if not parts:
        return

    insert_block = "\n".join(parts)
    # 在 </body> 前插入
    if "</body>" in html:
        new_html = html.replace("</body>", insert_block + "\n</body>", 1)
    else:
        new_html = html + insert_block

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(new_html)


def _write_fallback_html(report_data: dict, html_path: str) -> None:
    """当 generate_report 模块不可用时的兜底 HTML。"""
    metrics = report_data.get("metrics", {}) or {}
    test_summary = metrics.get("test_summary", {})
    total = test_summary.get("total", report_data.get("total", 0))
    passed = test_summary.get("passed", report_data.get("passed", 0))
    failed = test_summary.get("failed", report_data.get("failed", 0))
    pass_rate = test_summary.get("pass_rate", report_data.get("pass_rate", 0.0))

    breakdown = metrics.get("capability_breakdown", [])
    breakdown_rows = "".join(
        f"<tr><td>{b['capability']}</td><td>{b['passed']}</td>"
        f"<td>{b['failed']}</td><td>{b['duration']}s</td></tr>"
        for b in breakdown
    )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>每日回归报告</title></head>
<body>
<h1>每日回归测试报告</h1>
<p>生成时间: {report_data.get('generated_at', '')}</p>
<p>总数: {total} | 通过: {passed} | 失败: {failed} | 通过率: {pass_rate * 100:.2f}%</p>
<h2>能力点 Breakdown</h2>
<table border="1">
<tr><th>能力</th><th>通过</th><th>失败</th><th>耗时</th></tr>
{breakdown_rows}
</table>
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
    """执行每日回归测试完整流程（覆盖 W1-W3 能力 + 退化检测 + 趋势）。

    Args:
        module: 测试模块名（None 表示全部；当前仅用于报告标记，不再过滤 E2E 模块）
        host: 后端服务地址
        port: 后端服务端口
        notify: 失败时是否发送通知
        skip_server_start: 跳过启动后端（用于服务已运行时）

    Returns:
        包含 report_data / json_path / html_path / exit_code 的字典
    """
    print("=" * 60)
    print("  每日回归测试（Task 11: 连续回归测试闭环）")
    print(f"  模块: {module or 'all'}")
    print(f"  服务: http://{host}:{port}")
    print(f"  通知: {'开启' if notify else '关闭'}")
    print("=" * 60)

    proc: subprocess.Popen | None = None
    started_local_server = False

    # 1. 启动后端服务
    if not skip_server_start:
        print("\n[1/8] 启动后端服务...")
        env = os.environ.copy()
        env["PYTHONPATH"] = str(_PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        cmd = _build_uvicorn_command(host, port)
        try:
            if os.name == "nt":
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
            started_local_server = True
        except Exception as e:
            print(f"[error] 启动后端服务失败: {e}")
            return {"exit_code": 1, "error": f"启动后端失败: {e}"}
    else:
        print("\n[1/8] 跳过后端启动（--skip-server-start）")

    # 2. 等待服务就绪（若启动了本地服务）
    if started_local_server:
        print("\n[2/8] 等待服务就绪（最多 30s）...")
        ready = _wait_for_service(host, port, timeout=30.0)
        if not ready:
            print("[error] 后端服务 30s 内未就绪")
            if proc is not None:
                _terminate_process(proc)
            return {"exit_code": 1, "error": "后端服务就绪超时"}
        print("[ok] 后端服务已就绪")
    else:
        print("\n[2/8] 跳过服务就绪检查（未启动本地服务）")

    # 3. 运行后端单元测试 + E2E 测试套件
    unit_exit, unit_report = _run_unit_tests()
    e2e_exit, e2e_report = _run_e2e_suite()

    # 4. 构建能力点 breakdown
    print("\n[4/8] 聚合 W1-W3 能力点 breakdown...")
    capability_breakdown = _build_capability_breakdown(unit_report, e2e_report)
    cap_pass = sum(1 for b in capability_breakdown if b["status"] == "pass")
    cap_fail = sum(1 for b in capability_breakdown if b["status"] == "fail")
    print(
        f"[ok] 能力点汇总: {cap_pass} 通过 / {cap_fail} 失败 / "
        f"{len(capability_breakdown)} 总数"
    )

    # 5. 拉取运行时指标
    print("\n[5/8] 拉取运行时指标（/api/monitoring/health）...")
    runtime_metrics = _fetch_runtime_metrics(host, port)
    if runtime_metrics == "unavailable":
        print("[info] 运行时指标不可用（服务未运行或需鉴权）")
    else:
        print(f"[ok] 运行时指标已获取（策略数: {runtime_metrics.get('strategy_count', 0)}）")

    # 6. 退化检测（对比前一日报告）
    print("\n[6/8] 退化检测（对比前一日报告）...")
    today = datetime.now()
    prev_path = _find_previous_report(today)
    regressions: list[dict] = []
    if prev_path is not None:
        print(f"[info] 前一日报告: {prev_path.name}")
        try:
            with open(prev_path, "r", encoding="utf-8") as f:
                prev_data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[warn] 读取前一日报告失败: {e}")
            prev_data = {}
    else:
        print("[info] 未找到前一日报告，跳过退化检测")
        prev_data = {}

    # 7. 聚合 7/30 天趋势
    print("\n[7/8] 聚合 7/30 天趋势...")
    trend_data = _build_trend_data()
    trend_ascii = _render_ascii_trend(trend_data)
    print("[ok] 趋势数据已聚合")
    print(trend_ascii)

    # 8. 组装最终报告 + 写入文件
    print("\n[8/8] 组装并写入报告...")

    # 汇总测试统计（聚合 unit + e2e）
    total_total = unit_report.get("total", 0) + e2e_report.get("total", 0)
    total_passed = unit_report.get("passed", 0) + e2e_report.get("passed", 0)
    total_failed = unit_report.get("failed", 0) + e2e_report.get("failed", 0)
    total_errors = unit_report.get("errors", 0) + e2e_report.get("errors", 0)
    total_skipped = unit_report.get("skipped", 0) + e2e_report.get("skipped", 0)
    total_duration = round(
        unit_report.get("duration_seconds", 0) + e2e_report.get("duration_seconds", 0), 2
    )
    total_pass_rate = round(total_passed / total_total, 4) if total_total > 0 else 0.0

    # 合并失败项
    merged_failures = []
    for f in unit_report.get("failures", []):
        f_copy = dict(f)
        f_copy["suite"] = "unit"
        merged_failures.append(f_copy)
    for f in e2e_report.get("failures", []):
        f_copy = dict(f)
        f_copy["suite"] = "e2e"
        merged_failures.append(f_copy)

    # 计算合并退出码（任一套件失败即视为失败）
    exit_code = 0 if (unit_exit == 0 and e2e_exit == 0) else 1

    report_data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "module": module or "all",
        "total": total_total,
        "passed": total_passed,
        "failed": total_failed,
        "errors": total_errors,
        "skipped": total_skipped,
        "pass_rate": total_pass_rate,
        "duration_seconds": total_duration,
        "failures": merged_failures,
        "summary": (
            f"{total_passed}/{total_total} passed ({total_pass_rate * 100:.2f}%)"
            + (f", {total_skipped} skipped" if total_skipped else "")
            + (f", {total_errors} errors" if total_errors else "")
        ),
        "metrics": {
            "test_summary": {
                "total": total_total,
                "passed": total_passed,
                "failed": total_failed,
                "errors": total_errors,
                "skipped": total_skipped,
                "pass_rate": total_pass_rate,
                "duration": total_duration,
            },
            "unit_tests": {
                "total": unit_report.get("total", 0),
                "passed": unit_report.get("passed", 0),
                "failed": unit_report.get("failed", 0),
                "errors": unit_report.get("errors", 0),
                "skipped": unit_report.get("skipped", 0),
                "pass_rate": unit_report.get("pass_rate", 0.0),
                "duration": unit_report.get("duration_seconds", 0),
                "exit_code": unit_exit,
            },
            "e2e_tests": {
                "total": e2e_report.get("total", 0),
                "passed": e2e_report.get("passed", 0),
                "failed": e2e_report.get("failed", 0),
                "errors": e2e_report.get("errors", 0),
                "skipped": e2e_report.get("skipped", 0),
                "pass_rate": e2e_report.get("pass_rate", 0.0),
                "duration": e2e_report.get("duration_seconds", 0),
                "exit_code": e2e_exit,
            },
            "capability_breakdown": capability_breakdown,
            "runtime_metrics": runtime_metrics,
        },
        "trend": trend_data,
        "trend_ascii": trend_ascii,
    }

    # 退化检测（基于已组装的 metrics）
    if prev_data:
        regressions = _detect_regressions(report_data, prev_data)
        if regressions:
            print(f"[regression] 检测到 {len(regressions)} 项退化:")
            for r in regressions:
                print(f"  - [{r['severity']}] {r['description']}")
            # 严重退化追加任务到 tasks.md
            _append_regression_tasks(regressions, today)
        else:
            print("[ok] 无退化项")
    report_data["regressions"] = regressions

    # 写报告
    json_path, html_path = _write_daily_report(report_data, module)
    print(f"[ok] JSON 报告: {json_path}")
    print(f"[ok] HTML 报告: {html_path}")

    # 关闭后端服务
    if proc is not None:
        print("\n[final] 关闭后端服务...")
        _terminate_process(proc)
        print("[ok] 后端服务已关闭")

    # 通知
    has_failure = total_failed > 0 or total_errors > 0
    if notify and has_failure:
        print("\n[notify] 发送失败通知...")
        await _send_failure_notification(report_data, module)

    # 控制台汇总
    print("\n" + "=" * 60)
    print("  每日回归测试完成")
    print(f"  摘要: {report_data.get('summary', '')}")
    print(f"  通过率: {total_pass_rate * 100:.2f}%")
    print(f"  耗时: {total_duration}s")
    print(f"  能力点: {cap_pass}/{len(capability_breakdown)} 通过")
    print(f"  退化项: {len(regressions)}")
    print(f"  报告: {json_path}")
    print("=" * 60)

    return {
        "exit_code": exit_code,
        "report_data": report_data,
        "json_path": json_path,
        "html_path": html_path,
    }


# ============================================================
# 长期运行模式（Task 11.5）
# ============================================================


def _next_run_timestamp(daily_hour: int) -> float:
    """计算下一次执行时刻的 timestamp（默认次日凌晨 daily_hour 点）。"""
    now = datetime.now()
    next_run = now.replace(hour=daily_hour, minute=0, second=0, microsecond=0)
    if next_run <= now:
        next_run = next_run + timedelta(days=1)
    return next_run.timestamp()


def run_continuous(
    daily_hour: int = DEFAULT_DAILY_HOUR,
    module: str | None = None,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    notify: bool = False,
    skip_server_start: bool = False,
) -> None:
    """常驻模式：每日定时执行一次回归。

    使用 time.sleep 等待至下次执行时刻，循环执行直至被 Ctrl+C 中断。
    不依赖第三方 schedule 库，避免引入新依赖。
    """
    print("=" * 60)
    print("  连续回归测试 - 常驻模式")
    print(f"  每日执行时刻: {daily_hour:02d}:00（本地时区）")
    print(f"  按 Ctrl+C 退出")
    print("=" * 60)

    try:
        while True:
            next_ts = _next_run_timestamp(daily_hour)
            wait_seconds = max(0.0, next_ts - time.time())
            next_dt = datetime.fromtimestamp(next_ts)
            print(
                f"\n[continuous] 下次执行: {next_dt.strftime('%Y-%m-%d %H:%M:%S')} "
                f"（等待 {wait_seconds:.0f}s）"
            )

            # 分段 sleep 以便响应 Ctrl+C
            while time.time() < next_ts:
                try:
                    time.sleep(min(30.0, next_ts - time.time()))
                except KeyboardInterrupt:
                    raise

            print(f"\n[continuous] 开始执行 ({datetime.now().isoformat()})")
            try:
                asyncio.run(
                    run_regression(
                        module=module,
                        host=host,
                        port=port,
                        notify=notify,
                        skip_server_start=skip_server_start,
                    )
                )
            except Exception as e:
                print(f"[continuous] 单次执行异常（不中断循环）: {e}")

    except KeyboardInterrupt:
        print("\n[continuous] 收到 Ctrl+C，退出常驻模式")


# ============================================================
# CLI
# ============================================================


def main():
    parser = argparse.ArgumentParser(
        description=(
            "每日回归测试脚本（Task 11: 连续回归测试闭环）。"
            "覆盖 W1-W3 全部能力点、退化检测、7/30 天趋势。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 单次运行（默认）
  python scripts/daily_regression.py --once

  # 常驻每日 02:00 执行
  python scripts/daily_regression.py --continuous

  # 自定义常驻执行时刻（每日 04:30）
  python scripts/daily_regression.py --continuous --daily-hour 4

  # 失败时发送通知
  python scripts/daily_regression.py --once --notify

  # 服务已运行时跳过启动
  python scripts/daily_regression.py --once --skip-server-start

长期运行建议:
  - Linux cron: 0 2 * * * cd /path/to/quant_okx && python scripts/daily_regression.py --once
  - Windows 计划任务: 每日 02:00 启动 "python scripts\\daily_regression.py --once"
  - 或直接 --continuous 常驻运行（适合容器化部署）
        """,
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--once",
        action="store_true",
        default=True,
        help="单次运行模式（默认）",
    )
    mode_group.add_argument(
        "--continuous",
        action="store_true",
        help="常驻模式：每日定时执行（默认 02:00）",
    )
    parser.add_argument(
        "--daily-hour",
        type=int,
        default=DEFAULT_DAILY_HOUR,
        help=f"常驻模式的每日执行小时（0-23，默认 {DEFAULT_DAILY_HOUR}）",
    )
    parser.add_argument(
        "--module",
        default="all",
        help="测试模块（仅用于报告标记，默认 all）",
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

    if args.continuous:
        run_continuous(
            daily_hour=args.daily_hour,
            module=module,
            host=args.host,
            port=args.port,
            notify=args.notify,
            skip_server_start=args.skip_server_start,
        )
    else:
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
