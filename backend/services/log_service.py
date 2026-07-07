import os
import logging
from datetime import datetime
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)


def _get_log_path() -> Path:
    today = datetime.now().strftime("%Y-%m-%d")
    return LOG_DIR / f"api_{today}.log"


_file_logger: logging.Logger | None = None


def _get_logger() -> logging.Logger:
    global _file_logger
    if _file_logger is None:
        _file_logger = logging.getLogger("okx_api_file")
        _file_logger.setLevel(logging.INFO)
        _file_logger.handlers.clear()

        handler = logging.FileHandler(str(_get_log_path()), encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "[%(asctime)s] %(message)s",
            datefmt="%H:%M:%S",
        ))
        _file_logger.addHandler(handler)
        _file_logger.propagate = False
    else:
        current_path = str(_get_log_path())
        if _file_logger.handlers:
            handler = _file_logger.handlers[0]
            if hasattr(handler, "baseFilename") and handler.baseFilename != current_path:
                handler.close()
                _file_logger.handlers.clear()
                handler = logging.FileHandler(current_path, encoding="utf-8")
                handler.setFormatter(logging.Formatter(
                    "[%(asctime)s] %(message)s",
                    datefmt="%H:%M:%S",
                ))
                _file_logger.addHandler(handler)

    return _file_logger


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
        logger = _get_logger()
        req_short = request_body[:500] if request_body else ""
        resp_short = response_body[:500] if response_body else ""
        logger.info(
            f"[{account_name or '-'}] {method} {endpoint} "
            f"| code={response_code} status={status} "
            f"| req={req_short} "
            f"| resp={resp_short}"
        )
    except Exception:
        pass


def list_log_files() -> list[dict]:
    files = []
    if LOG_DIR.exists():
        for f in sorted(LOG_DIR.glob("api_*.log"), reverse=True):
            stat = f.stat()
            files.append({
                "name": f.name,
                "size": stat.st_size,
                "date": f.stem.replace("api_", ""),
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
    return files


def read_log_file(filename: str, tail_lines: int = 200) -> str:
    file_path = LOG_DIR / filename
    if not file_path.exists():
        return ""

    if ".." in filename or "/" in filename or "\\" in filename:
        return ""

    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    lines = lines[-tail_lines:]
    return "".join(lines)
