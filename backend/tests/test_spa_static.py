"""React SPA 静态路由回归测试。"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from spa_static import SPAStaticFiles


def _make_app(tmp_path):
    frontend_dir = tmp_path / "dist"
    assets_dir = frontend_dir / "assets"
    assets_dir.mkdir(parents=True)
    (frontend_dir / "index.html").write_text(
        '<!doctype html><div id="root">Q-Studio</div>',
        encoding="utf-8",
    )
    (assets_dir / "app.js").write_text(
        'console.log("Q-Studio")',
        encoding="utf-8",
    )

    app = FastAPI()

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    app.mount("/", SPAStaticFiles(directory=frontend_dir, html=True), name="static")
    return app


def test_spa_route_returns_root_index(tmp_path):
    client = TestClient(_make_app(tmp_path))

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'id="root"' in response.text


def test_nested_spa_route_returns_root_index(tmp_path):
    client = TestClient(_make_app(tmp_path))

    response = client.get("/strategies/123")

    assert response.status_code == 200
    assert 'id="root"' in response.text


def test_existing_asset_is_still_served(tmp_path):
    client = TestClient(_make_app(tmp_path))

    response = client.get("/assets/app.js")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    assert "Q-Studio" in response.text


def test_missing_asset_stays_404(tmp_path):
    client = TestClient(_make_app(tmp_path))

    response = client.get("/assets/missing.js")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_api_routes_are_not_replaced_by_index(tmp_path):
    client = TestClient(_make_app(tmp_path))

    health_response = client.get("/api/health")
    missing_response = client.get("/api/missing")

    assert health_response.status_code == 200
    assert health_response.json() == {"status": "ok"}
    assert missing_response.status_code == 404
    assert missing_response.json() == {"detail": "Not Found"}


def test_missing_file_with_extension_stays_404(tmp_path):
    client = TestClient(_make_app(tmp_path))

    response = client.get("/favicon.ico")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_head_request_to_spa_route_returns_html_headers(tmp_path):
    client = TestClient(_make_app(tmp_path))

    response = client.head("/dashboard")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
