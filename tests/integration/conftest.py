"""Fixtures e helpers compartilhados pelos testes de integração da agenda."""

import pytest

from tests.integration.test_courts_postgres import COURT, account

DAY = "2030-01-10"


def at(clock: str) -> str:
    return f"{DAY}T{clock}:00-03:00"


@pytest.fixture
def agenda(member_admin_client):
    """Admin (Maria), duas contas comuns (Bruno e Carla) e uma quadra para até 4 jogadores."""
    client, admin = member_admin_client
    court = client.post("/api/v1/courts", headers=admin, json=COURT).json()["data"]
    bruno = account(client, "Bruno", "bruno@example.com")
    carla = account(client, "Carla", "carla@example.com")
    ids = {
        name: client.get("/api/v1/auth/me", headers=headers).json()["data"]["id"]
        for name, headers in {"admin": admin, "bruno": bruno, "carla": carla}.items()
    }

    def book(headers, start, duration=60, **extra):
        return client.post(
            "/api/v1/bookings",
            headers=headers,
            json={
                "court_id": court["id"],
                "starts_at": at(start),
                "duration_minutes": duration,
                **extra,
            },
        )

    return client, court, {"admin": admin, "bruno": bruno, "carla": carla}, ids, book


def maintenance(client, headers, court_id, start, end, **extra):
    return client.post(
        f"/api/v1/courts/{court_id}/maintenance",
        headers=headers,
        json={"starts_at": at(start), "ends_at": at(end), "reason": " Troca do saibro ", **extra},
    )
