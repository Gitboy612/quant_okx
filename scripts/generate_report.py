"""测试报告生成器。

读取 JSON 测试报告，生成 HTML 格式报告：
- 测试摘要（通过率 / 失败数 / 耗时）
- 失败详情（测试名 / 错误信息 / 堆栈）
- 历史趋势图（最近 7 天的通过率，使用内联 SVG，无外部依赖）

HTML 模板完全内联，不依赖任何外部文件或 CDN。

用法：
    python scripts/generate_report.py <json_report_path> [--output <html_path>]
    python scripts/generate_report.py backend/tests/reports/daily_regression_20260101_120000.json

也可作为模块导入：
    from generate_report import generate_html_report
    generate_html_report(report_data, html_path)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
_REPORTS_DIR = _PROJECT_ROOT / "backend" / "tests" / "reports"


# ============================================================
# 历史数据加载
# ============================================================


def _load_recent_reports(reports_dir: Path, days: int = 7) -> list[dict]:
    """加载最近 N 天的 JSON 报告，按时间正序返回。

    匹配 e2e_report_*.json 与 daily_regression_*.json 两类报告。
    解析失败或缺少 generated_at 的报告会被跳过。
    """
    if not reports_dir.exists():
        return []

    candidates: list[tuple[float, dict]] = []
    now_ts = datetime.now(timezone.utc).timestamp()
    cutoff = now_ts - days * 86400

    for pattern in ("e2e_report_*.json", "daily_regression_*.json"):
        for fp in reports_dir.glob(pattern):
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

            ts_str = data.get("generated_at") or data.get("generated_at_local", "")
            try:
                # 兼容带 Z 与 +00:00 的 ISO 格式
                normalized = ts_str.replace("Z", "+00:00") if ts_str else ""
                dt = datetime.fromisoformat(normalized)
                ts = dt.timestamp()
            except (ValueError, TypeError):
                # 回退：用文件修改时间
                ts = fp.stat().st_mtime

            if ts < cutoff:
                continue
            # 注入文件级时间戳，便于排序
            data["_sort_ts"] = ts
            candidates.append((ts, data))

    candidates.sort(key=lambda x: x[0])
    return [d for _, d in candidates]


def _build_trend_points(reports: list[dict]) -> list[dict]:
    """从历史报告列表构建趋势点 [{date, pass_rate, total, passed}]。"""
    points: list[dict] = []
    for r in reports:
        ts = r.get("_sort_ts")
        if ts is None:
            continue
        try:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            date_label = dt.strftime("%m-%d")
        except (OSError, ValueError):
            date_label = "?"
        pass_rate = r.get("pass_rate", 0.0)
        if isinstance(pass_rate, str):
            try:
                pass_rate = float(pass_rate)
            except ValueError:
                pass_rate = 0.0
        points.append({
            "date": date_label,
            "pass_rate": round(float(pass_rate), 4),
            "total": r.get("total", 0),
            "passed": r.get("passed", 0),
        })
    return points


# ============================================================
# 内联 SVG 趋势图
# ============================================================


def _render_trend_svg(points: list[dict], width: int = 640, height: int = 200) -> str:
    """渲染通过率趋势图为内联 SVG（无外部依赖）。

    坐标系：
    - x: 0 ~ width，按点数均匀分布
    - y: height ~ 0，对应 0% ~ 100% 通过率
    """
    if not points:
        return '<p style="color:#999;text-align:center;">暂无历史数据</p>'

    pad_left = 48
    pad_right = 16
    pad_top = 16
    pad_bottom = 32
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    n = len(points)
    # x 坐标
    xs = []
    for i in range(n):
        if n == 1:
            xs.append(pad_left + plot_w / 2)
        else:
            xs.append(pad_left + plot_w * i / (n - 1))

    # y 坐标（0% 在底部，100% 在顶部）
    def y_of(rate: float) -> float:
        return pad_top + plot_h * (1.0 - rate)

    ys = [y_of(p["pass_rate"]) for p in points]

    # 折线路径
    line_path = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))

    # 填充区域路径（折线 + 底部）
    area_path = (
        f"M {xs[0]:.1f},{pad_top + plot_h:.1f} "
        + " ".join(f"L {x:.1f},{y:.1f}" for x, y in zip(xs, ys))
        + f" L {xs[-1]:.1f},{pad_top + plot_h:.1f} Z"
    )

    # 坐标轴与网格线
    grid_lines = []
    labels_y = []
    for pct in (0, 25, 50, 75, 100):
        gy = y_of(pct / 100.0)
        grid_lines.append(
            f'<line x1="{pad_left}" y1="{gy:.1f}" x2="{width - pad_right}" '
            f'y2="{gy:.1f}" stroke="#eee" stroke-width="1"/>'
        )
        labels_y.append(
            f'<text x="{pad_left - 6}" y="{gy + 4:.1f}" text-anchor="end" '
            f'font-size="10" fill="#999">{pct}%</text>'
        )

    # x 轴日期标签
    labels_x = []
    step = max(1, n // 7)  # 最多显示 7 个标签避免重叠
    for i in range(0, n, step):
        labels_x.append(
            f'<text x="{xs[i]:.1f}" y="{height - pad_bottom + 16}" '
            f'text-anchor="middle" font-size="10" fill="#999">{points[i]["date"]}</text>'
        )

    # 数据点圆圈
    dots = []
    for x, y, p in zip(xs, ys, points):
        color = "#16a34a" if p["pass_rate"] >= 0.8 else ("#f59e0b" if p["pass_rate"] >= 0.5 else "#dc2626")
        dots.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{color}" '
            f'<title>{p["date"]} 通过率 {p["pass_rate"]*100:.1f}% ({p["passed"]}/{p["total"]})</title>'
            f'/>'
        )

    return f"""<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" style="max-width:100%;height:auto;">
  <defs>
    <linearGradient id="trendGradient" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#00D4AA" stop-opacity="0.25"/>
      <stop offset="100%" stop-color="#00D4AA" stop-opacity="0.02"/>
    </linearGradient>
  </defs>
  {''.join(grid_lines)}
  {''.join(labels_y)}
  <path d="{area_path}" fill="url(#trendGradient)"/>
  <polyline points="{line_path}" fill="none" stroke="#00D4AA" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
  {''.join(dots)}
  {''.join(labels_x)}
  <text x="{pad_left}" y="{pad_top - 4}" font-size="11" fill="#666" font-weight="bold">通过率趋势（最近 7 天）</text>
</svg>"""


# ============================================================
# HTML 渲染
# ============================================================


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
    background: #f7f8fa; color: #1f2937; line-height: 1.6; padding: 24px;
  }}
  .container {{ max-width: 960px; margin: 0 auto; }}
  .header {{
    background: linear-gradient(135deg, #00D4AA 0%, #00B894 100%);
    color: #fff; padding: 24px 32px; border-radius: 12px; margin-bottom: 24px;
    box-shadow: 0 2px 8px rgba(0, 212, 170, 0.15);
  }}
  .header h1 {{ font-size: 22px; margin-bottom: 8px; }}
  .header .meta {{ font-size: 13px; opacity: 0.9; }}
  .summary-grid {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 16px; margin-bottom: 24px;
  }}
  .summary-card {{
    background: #fff; border-radius: 10px; padding: 20px; text-align: center;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
  }}
  .summary-card .value {{ font-size: 28px; font-weight: 700; margin-bottom: 4px; }}
  .summary-card .label {{ font-size: 12px; color: #6b7280; }}
  .summary-card.pass .value {{ color: #16a34a; }}
  .summary-card.fail .value {{ color: #dc2626; }}
  .summary-card.rate .value {{ color: #00B894; }}
  .summary-card.duration .value {{ color: #6366f1; font-size: 22px; }}
  .section {{
    background: #fff; border-radius: 10px; padding: 24px; margin-bottom: 24px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
  }}
  .section h2 {{ font-size: 16px; margin-bottom: 16px; color: #374151; border-left: 3px solid #00D4AA; padding-left: 10px; }}
  .failure-item {{
    border: 1px solid #fee2e2; background: #fef2f2; border-radius: 8px;
    padding: 14px 16px; margin-bottom: 12px;
  }}
  .failure-item .ftitle {{ font-weight: 600; color: #dc2626; margin-bottom: 6px; font-size: 14px; }}
  .failure-item .fmeta {{ font-size: 12px; color: #9ca3af; margin-bottom: 8px; }}
  .failure-item pre {{
    background: #fff; border: 1px solid #e5e7eb; border-radius: 6px;
    padding: 10px; font-size: 12px; color: #4b5563; overflow-x: auto;
    white-space: pre-wrap; word-break: break-word; max-height: 320px; overflow-y: auto;
  }}
  .no-failure {{
    text-align: center; color: #16a34a; padding: 32px; font-size: 14px;
  }}
  .trend-chart {{ margin-top: 8px; }}
  .footer {{
    text-align: center; color: #9ca3af; font-size: 12px; padding: 16px;
  }}
  .badge {{
    display: inline-block; padding: 2px 10px; border-radius: 12px;
    font-size: 11px; font-weight: 600;
  }}
  .badge.passed {{ background: #dcfce7; color: #16a34a; }}
  .badge.failed {{ background: #fee2e2; color: #dc2626; }}
  .badge.error {{ background: #fef3c7; color: #d97706; }}
  .badge.skipped {{ background: #f3f4f6; color: #6b7280; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>📊 {title}</h1>
    <div class="meta">{meta_line}</div>
  </div>

  <div class="summary-grid">
    <div class="summary-card rate">
      <div class="value">{pass_rate_pct}%</div>
      <div class="label">通过率</div>
    </div>
    <div class="summary-card pass">
      <div class="value">{passed}</div>
      <div class="label">通过</div>
    </div>
    <div class="summary-card fail">
      <div class="value">{failed}</div>
      <div class="label">失败</div>
    </div>
    <div class="summary-card">
      <div class="value">{errors}</div>
      <div class="label">错误</div>
    </div>
    <div class="summary-card">
      <div class="value">{skipped}</div>
      <div class="label">跳过</div>
    </div>
    <div class="summary-card duration">
      <div class="value">{duration}s</div>
      <div class="label">总耗时</div>
    </div>
  </div>

  <div class="section">
    <h2>失败详情</h2>
    {failure_html}
  </div>

  <div class="section">
    <h2>历史趋势</h2>
    <div class="trend-chart">{trend_svg}</div>
    <p style="font-size:12px;color:#9ca3af;margin-top:12px;">
      共加载 {trend_count} 份历史报告（来自 backend/tests/reports/ 目录）
    </p>
  </div>

  <div class="footer">
    QuantOKX 量化交易平台 · 自动化测试报告 · 生成于 {generated_at}
  </div>
</div>
</body>
</html>"""


def _render_failures(failures: list[dict]) -> str:
    """渲染失败详情 HTML 片段。"""
    if not failures:
        return '<div class="no-failure">✅ 全部测试通过，无失败项</div>'

    items: list[str] = []
    for f in failures:
        module = f.get("module", "")
        test = f.get("test", "")
        outcome = f.get("outcome", "failed")
        duration = f.get("duration", 0)
        message = f.get("message", "")

        # 转义 HTML 特殊字符
        msg_safe = (
            message.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

        badge_class = "failed" if outcome == "failed" else "error"
        items.append(f"""<div class="failure-item">
  <div class="ftitle">[{module}] {test}</div>
  <div class="fmeta">
    <span class="badge {badge_class}">{outcome}</span>
    &nbsp;耗时 {duration}s
  </div>
  <pre>{msg_safe}</pre>
</div>""")

    return "\n".join(items)


def generate_html_report(report_data: dict, output_path: str | None = None) -> str:
    """根据 JSON 报告数据生成 HTML 报告。

    Args:
        report_data: 测试报告字典（来自 run_e2e_tests 或 daily_regression）
        output_path: HTML 输出路径；为 None 时不写文件

    Returns:
        HTML 字符串
    """
    total = report_data.get("total", 0)
    passed = report_data.get("passed", 0)
    failed = report_data.get("failed", 0)
    errors = report_data.get("errors", 0)
    skipped = report_data.get("skipped", 0)
    pass_rate = report_data.get("pass_rate", 0.0)
    if isinstance(pass_rate, str):
        try:
            pass_rate = float(pass_rate)
        except ValueError:
            pass_rate = 0.0
    duration = report_data.get("duration_seconds", 0.0)
    failures = report_data.get("failures", [])
    generated_at = report_data.get("generated_at", "")
    module = report_data.get("module", "all")
    report_type = report_data.get("report_type", "e2e")

    # 标题
    if report_type == "daily_regression":
        title = "每日回归测试报告"
    else:
        title = "E2E 测试报告"
    meta_line = f"模块: {module} · 生成时间: {generated_at}"

    # 失败详情
    failure_html = _render_failures(failures)

    # 历史趋势
    trend_points = _build_trend_points(_load_recent_reports(_REPORTS_DIR, days=7))
    trend_svg = _render_trend_svg(trend_points)
    trend_count = len(trend_points)

    html = _HTML_TEMPLATE.format(
        title=title,
        meta_line=meta_line,
        pass_rate_pct=f"{pass_rate * 100:.2f}",
        passed=passed,
        failed=failed,
        errors=errors,
        skipped=skipped,
        duration=f"{duration:.1f}",
        failure_html=failure_html,
        trend_svg=trend_svg,
        trend_count=trend_count,
        generated_at=generated_at,
    )

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)

    return html


# ============================================================
# CLI
# ============================================================


def main():
    parser = argparse.ArgumentParser(
        description="测试报告生成器：读取 JSON 报告，生成 HTML（含历史趋势图）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/generate_report.py backend/tests/reports/daily_regression_20260101_120000.json
  python scripts/generate_report.py report.json --output report.html
        """,
    )
    parser.add_argument("json_path", help="JSON 测试报告路径")
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="HTML 输出路径（默认与 JSON 同名 .html）",
    )
    args = parser.parse_args()

    json_path = Path(args.json_path)
    if not json_path.exists():
        print(f"[error] 报告文件不存在: {json_path}")
        sys.exit(1)

    with open(json_path, "r", encoding="utf-8") as f:
        report_data = json.load(f)

    output_path = args.output or str(json_path.with_suffix(".html"))
    generate_html_report(report_data, output_path)
    print(f"[ok] HTML 报告已生成: {output_path}")


if __name__ == "__main__":
    main()
