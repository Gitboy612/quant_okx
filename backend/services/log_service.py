import os
import logging
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"

CATEGORIES = ["all", "error", "query", "order"]
_loggers: dict[str, logging.Logger] = {}
_current_paths: dict[str, str] = {}


def _ensure_dir(dir_path: Path):
    dir_path.mkdir(parents=True, exist_ok=True)


def _get_log_path(category: str) -> Path:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    dir_path = LOG_DIR / category
    _ensure_dir(dir_path)
    return dir_path / f"api_{today}.log"


def _get_logger(category: str) -> logging.Logger:
    global _loggers, _current_paths

    if category not in _loggers:
        logger = logging.getLogger(f"okx_api_{category}")
        logger.setLevel(logging.INFO)
        logger.handlers.clear()

        path = _get_log_path(category)
        handler = logging.FileHandler(str(path), encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "[%(asctime)s] %(message)s",
            datefmt="%H:%M:%S",
        ))
        logger.addHandler(handler)
        logger.propagate = False
        _loggers[category] = logger
        _current_paths[category] = str(path)
        return logger

    current_path = str(_get_log_path(category))
    logger = _loggers[category]
    if _current_paths.get(category) != current_path:
        if logger.handlers:
            handler = logger.handlers[0]
            if hasattr(handler, "baseFilename"):
                handler.close()
            logger.handlers.clear()
        handler = logging.FileHandler(current_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "[%(asctime)s] %(message)s",
            datefmt="%H:%M:%S",
        ))
        logger.addHandler(handler)
        _current_paths[category] = current_path

    return logger


def _classify_log(method: str, endpoint: str, status: str) -> list[str]:
    """Determine which categories this log entry belongs to."""
    categories = ["all"]

    if status in ("error", "exception", "empty_response", "network_error"):
        categories.append("error")

    if method == "GET":
        categories.append("query")

    if method == "POST":
        ep_lower = endpoint.lower()
        if any(kw in ep_lower for kw in ("order", "cancel", "batch-orders")):
            categories.append("order")

    return categories


def log_api_call(
    account_name: str | None,
    method: str,
    endpoint: str,
    status: str,
    response_code: str,
    request_body: str,
    response_body: str,
):
    try:
        req_short = request_body[:500] if request_body else ""
        resp_short = response_body[:500] if response_body else ""
        msg = (
            f"[{account_name or '-'}] {method} {endpoint} "
            f"| code={response_code} status={status} "
            f"| req={req_short} "
            f"| resp={resp_short}"
        )

        categories = _classify_log(method, endpoint, status)
        for cat in categories:
            logger = _get_logger(cat)
            logger.info(msg)
    except Exception:
        pass


def list_log_files(category: str = "all") -> list[dict]:
    files = []
    dir_path = LOG_DIR / category
    if dir_path.exists():
        for f in sorted(dir_path.glob("api_*.log"), reverse=True):
            stat = f.stat()
            files.append({
                "name": f.name,
                "size": stat.st_size,
                "date": f.stem.replace("api_", ""),
                "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            })
    return files


def read_log_file(filename: str, category: str = "all", tail_lines: int = 200) -> str:
    file_path = LOG_DIR / category / filename
    if not file_path.exists():
        return ""

    if ".." in filename or "/" in filename or "\\" in filename:
        return ""

    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    lines = lines[-tail_lines:]
    return "".join(lines)