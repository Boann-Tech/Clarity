"""CORS policy tests for Chrome-extension requests."""

from fastapi.testclient import TestClient


def test_chrome_extension_preflight_is_allowed():
    from app.main import app

    client = TestClient(app)
    response = client.options(
        "/api/check",
        headers={
            "Origin": "chrome-extension://abcdefghijklmnopabcdefghijklmnop",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == (
        "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
    )
