import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

ENDPOINTS = [
    ("POST", "/api/v1/courts", {}),
    ("GET", "/api/v1/courts", None),
    ("GET", "/api/v1/courts/1", None),
    ("PATCH", "/api/v1/courts/1", {"name": "X"}),
    ("DELETE", "/api/v1/courts/1", None),
    ("POST", "/api/v1/courts/1/maintenance", {}),
    ("DELETE", "/api/v1/courts/1/maintenance/1", None),
    ("POST", "/api/v1/bookings", {}),
    ("GET", "/api/v1/bookings", None),
    ("GET", "/api/v1/bookings/1", None),
    ("PATCH", "/api/v1/bookings/1", {}),
    ("POST", "/api/v1/bookings/1/cancel", None),
    ("DELETE", "/api/v1/bookings/1", None),
]


@pytest.fixture
def anonymous_client():
    with TestClient(create_app(Settings(_env_file=None))) as client:
        yield client


@pytest.mark.parametrize(("method", "path", "payload"), ENDPOINTS)
def test_court_and_booking_routes_require_login(anonymous_client, method, path, payload):
    response = anonymous_client.request(method, path, json=payload)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.headers["Cache-Control"] == "no-store"
