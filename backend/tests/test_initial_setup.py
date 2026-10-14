"""首次管理员设置的安全边界与已有账号兼容性。"""

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from models.user import User
from models.log import OperationLog  # noqa: F401 -- 注册外键表
from routers.auth import router
from services.auth_service import verify_password


def _client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    app = FastAPI()
    app.include_router(router)

    @app.middleware("http")
    async def simulate_client_address(request: Request, call_next):
        # TestClient 默认使用主机名 testclient；模拟真实连接的来源 IP。
        host = "192.0.2.1" if request.headers.get("x-test-remote") else "127.0.0.1"
        request.scope["client"] = (host, 50000)
        return await call_next(request)

    def override_db():
        db = sessions()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    return TestClient(app, base_url="http://127.0.0.1"), sessions


def test_initial_setup_creates_user_and_allows_login():
    client, sessions = _client()
    assert client.get("/api/auth/setup-status").json() == {"setup_required": True}

    response = client.post("/api/auth/setup", json={
        "password": "my-unique-passphrase", "confirm_password": "my-unique-passphrase",
    })
    assert response.status_code == 200
    assert response.json()["access_token"]
    assert client.get("/api/auth/setup-status").json() == {"setup_required": False}

    with sessions() as db:
        user = db.query(User).one()
        assert user.username == "admin"
        assert user.password_hash != "my-unique-passphrase"
        assert verify_password("my-unique-passphrase", user.password_hash)

    login = client.post("/api/auth/login", json={
        "username": "admin", "password": "my-unique-passphrase",
    })
    assert login.status_code == 200
    assert client.get("/api/auth/me", headers={
        "Authorization": f"Bearer {login.json()['access_token']}",
    }).json()["username"] == "admin"

    repeat = client.post("/api/auth/setup", json={
        "password": "other-passphrase", "confirm_password": "other-passphrase",
    })
    assert repeat.status_code == 409


def test_initial_setup_rejects_remote_and_invalid_password():
    client, _ = _client()
    payload = {"password": "secure-passphrase", "confirm_password": "secure-passphrase"}
    assert client.post("/api/auth/setup", json=payload, headers={"x-test-remote": "1"}).status_code == 403
    assert client.post("/api/auth/setup", json={
        "password": "short", "confirm_password": "short",
    }).status_code == 400
    assert client.post("/api/auth/setup", json={
        "password": "secure-passphrase", "confirm_password": "different-password",
    }).status_code == 400
    assert client.get("/api/auth/setup-status").json() == {"setup_required": True}


def test_existing_account_keeps_password():
    client, sessions = _client()
    from services.auth_service import hash_password
    with sessions() as db:
        db.add(User(username="admin", password_hash=hash_password("existing-password")))
        db.commit()

    assert client.get("/api/auth/setup-status").json() == {"setup_required": False}
    assert client.post("/api/auth/setup", json={
        "password": "new-password", "confirm_password": "new-password",
    }).status_code == 409
    assert client.post("/api/auth/login", json={
        "username": "admin", "password": "existing-password",
    }).status_code == 200
