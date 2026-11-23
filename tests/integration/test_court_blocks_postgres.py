"""US28: bloqueio de horários por manutenção ou evento."""

import pytest

from tests.integration.conftest import DAY, at, maintenance

pytestmark = pytest.mark.integration


def test_event_block_is_listed_with_its_kind_and_blocks_bookings(agenda):
    client, court, users, _, book = agenda
    response = maintenance(client, users["admin"], court["id"], "08:00", "12:00", kind="event")
    assert response.status_code == 201
    blocks = response.json()["data"]["maintenance"]
    assert [(item["kind"], item["reason"]) for item in blocks] == [("event", "Troca do saibro")]

    refused = book(users["bruno"], "09:00")
    assert refused.status_code == 409
    assert refused.json()["message"] == "Essa quadra está em manutenção nesse horário."

    schedule = client.get(f"/api/v1/schedule?date={DAY}", headers=users["bruno"]).json()["data"]
    blocked = {slot["starts_at"] for slot in schedule["slots"] if slot["status"] == "maintenance"}
    assert "2030-01-10T12:00:00Z" in blocked  # 09:00 em São Paulo


def test_kind_defaults_to_maintenance_and_is_validated(agenda):
    client, court, users, _, _ = agenda
    created = maintenance(client, users["admin"], court["id"], "08:00", "09:00")
    assert created.json()["data"]["maintenance"][0]["kind"] == "maintenance"

    invalid = client.post(
        f"/api/v1/courts/{court['id']}/maintenance",
        headers=users["admin"],
        json={"starts_at": at("10:00"), "ends_at": at("11:00"), "reason": "Festa", "kind": "festa"},
    )
    assert invalid.status_code == 422
    assert "kind" in invalid.json()["errors"]
