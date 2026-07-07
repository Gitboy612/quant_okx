import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DATABASE_URL = f"sqlite+aiosqlite:///{DATA_DIR / 'quant_okx.db'}"

KEY_FILE = DATA_DIR / ".encryption_key"

ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24
JWT_ALGORITHM = "HS256"
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "quant-okx-secret-key-change-in-production")

OKX_BASE_URL = os.getenv("OKX_BASE_URL", "https://openapi.okx.com")

OKX_ALT_URLS = os.getenv("OKX_ALT_URLS", "https://www.okx.cab,https://aws.okx.com").split(",")

OKX_DNS_OVERRIDE = os.getenv("OKX_DNS_OVERRIDE", "")

FRONTEND_DIR = BASE_DIR / "frontend" / "dist"

LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_MINUTES = 15
