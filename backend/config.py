import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

IS_FROZEN = getattr(sys, "frozen", False)

if IS_FROZEN:
    # PyInstaller 打包后：exe 所在目录作为 BASE_DIR
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent.parent

if IS_FROZEN:
    # 打包后数据放到 %APPDATA%/QuantOKX/data（用户数据持久化目录）
    DATA_DIR = Path(os.getenv("APPDATA", str(BASE_DIR))) / "QuantOKX" / "data"
else:
    DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = f"sqlite+aiosqlite:///{DATA_DIR / 'quant_okx.db'}"

KEY_FILE = DATA_DIR / ".encryption_key"

ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24
JWT_ALGORITHM = "HS256"
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "quant-okx-secret-key-change-in-production")

HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))
PRODUCTION = os.getenv("PRODUCTION", "").lower() in ("1", "true", "yes")

_CORS_ORIGINS_RAW = os.getenv("CORS_ORIGINS", "").strip()
CORS_ORIGINS = (
    [o.strip() for o in _CORS_ORIGINS_RAW.split(",") if o.strip()]
    if _CORS_ORIGINS_RAW
    else []
)

OKX_BASE_URL = os.getenv("OKX_BASE_URL", "https://openapi.okx.com")

OKX_ALT_URLS = os.getenv("OKX_ALT_URLS", "https://www.okx.cab,https://aws.okx.com").split(",")

OKX_DNS_OVERRIDE = os.getenv("OKX_DNS_OVERRIDE", "")

if IS_FROZEN:
    # 打包后前端从 _MEIPASS 读取（PyInstaller --add-data 解包临时目录）
    FRONTEND_DIR = Path(sys._MEIPASS) / "frontend" / "dist"
else:
    FRONTEND_DIR = BASE_DIR / "frontend" / "dist"

LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_MINUTES = 15
