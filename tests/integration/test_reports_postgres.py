"""US30: indicadores de ocupação das quadras."""

import pytest

from tests.integration.conftest import DAY, maintenance
from tests.integration.test_courts_postgres import COURT

pytestmark = pytest.mark.integration


def report(client, headers, start=DAY, end=DAY):
    return client.get(f"/api/v1/reports/occupancy?from={start}&to={end}", headers=headers)


def test_occupancy_by_court_weekday_and_hour(agenda):
    client, court, users, _, book = agenda
    other = client.post(
        "/api/v1/courts", headers=users["admin"], json={**COURT, "name": "Quadra 2"}
    ).json()["data"]
    assert book(users["bruno"], "19:00").status_code == 201  # 60 min
    assert book(users["carla"], "20:00", 90).status_code == 201  # 90 min, até 21:30
    cancelled = book(users["admin"], "10:00").json()["data"]
    client.post(f"/api/v1/bookings/{cancelled['id']}/cancel", headers=users["admin"])
    assert maintenance(client, users["admin"], court["id"], "08:00", "10:00").status_code == 201

    response = report(client, users["admin"])
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["period"] == {"from": DAY, "to": DAY, "days": 1}
    # 07:00-22:00 = 15 h por quadra; a quadra 1 perde 2 h de manutenção.
    assert data["totals"] == {
        "booked_hours": 2.5,
        "available_hours": 28.0,
        "occupancy_rate": round(150 / 1680, 4),
        "bookings": 2,
        "cancelled": 1,
    }
    first, second = data["courts"]
    assert first["court"] == {"id": court["id"], "name": court["name"]}
    assert first["booked_hours"] == 2.5
    assert first["available_hours"] == 13.0
    assert first["blocked_hours"] == 2.0
    assert first["bookings"] == 2
    assert first["occupancy_rate"] == round(150 / 780, 4)
    assert second["court"]["id"] == other["id"]
    assert second["occupancy_rate"] == 0.0

    weekdays = {item["weekday"]: item for item in data["by_weekday"]}
    assert weekdays[3]["booked_hours"] == 2.5  # 10/01/2030 é quinta-feira
    assert weekdays[0]["available_hours"] == 0.0

    hours = {item["hour"]: item for item in data["by_hour"]}
    assert sorted(hours) == list(range(7, 22))
    assert hours[19]["occupancy_rate"] == 0.5
    assert hours[21]["occupancy_rate"] == 0.25
    assert hours[8]["available_hours"] == 1.0  # só a quadra 2 estava livre


def test_period_validation_and_permissions(agenda):
    client, _, users, _, _ = agenda
    backwards = report(client, users["admin"], "2030-01-10", "2030-01-01")
    assert backwards.status_code == 422
    assert "from" in backwards.json()["errors"]
    too_long = report(client, users["admin"], "2030-01-01", "2030-06-01")
    assert too_long.status_code == 422
    assert report(client, users["bruno"]).status_code == 403

    default = client.get("/api/v1/reports/occupancy", headers=users["admin"])
    assert default.status_code == 200
    assert default.json()["data"]["period"]["days"] == 30
