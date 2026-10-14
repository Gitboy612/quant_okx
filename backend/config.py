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
JWT_SECRET_FILE = DATA_DIR / ".jwt_secret"

ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24
JWT_ALGORITHM = "HS256"

HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))
PRODUCTION = os.getenv("PRODUCTION", "").lower() in ("1", "true", "yes")

_INSECURE_JWT_SECRETS = frozenset({
    "",
    "quant-okx-secret-key-change-in-production",
    "change-this-to-a-random-secret-key",
})


def _load_or_create_jwt_secret() -> str:
    """Resolve JWT signing secret without hardcoded plaintext defaults.

    - In PRODUCTION: require an explicit, non-placeholder JWT_SECRET_KEY env var.
    - In development/desktop: use JWT_SECRET_KEY if set (and not a known placeholder);
      otherwise generate and persist a per-installation random secret in DATA_DIR.
    """
    import secrets

    env_secret = os.getenv("JWT_SECRET_KEY", "").strip()
    if PRODUCTION:
        if env_secret in _INSECURE_JWT_SECRETS or len(env_secret) < 32:
            raise RuntimeError(
                "PRODUCTION=true requires a strong JWT_SECRET_KEY (at least 32 chars) "
                "set via environment variable; refusing to start with default/weak secret."
            )
        return env_secret

    if env_secret and env_secret not in _INSECURE_JWT_SECRETS:
        return env_secret

    if JWT_SECRET_FILE.exists():
        stored = JWT_SECRET_FILE.read_text(encoding="utf-8").strip()
        if stored and stored not in _INSECURE_JWT_SECRETS:
            return stored

    generated = secrets.token_urlsafe(48)
    JWT_SECRET_FILE.write_text(generated, encoding="utf-8")
    try:
        os.chmod(JWT_SECRET_FILE, 0o600)
    except Exception:
        pass
    return generated


JWT_SECRET_KEY = _load_or_create_jwt_secret()

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
