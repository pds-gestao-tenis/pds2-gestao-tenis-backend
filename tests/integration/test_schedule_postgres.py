from datetime import UTC, datetime, timedelta

import pytest

from app.db.models import BookingModel
from tests.integration.conftest import DAY, at, maintenance
from tests.integration.test_courts_postgres import COURT, account

pytestmark = pytest.mark.integration


def schedule(client, headers, day=DAY):
    response = client.get(f"/api/v1/schedule?date={day}", headers=headers)
    assert response.status_code == 200
    return response.json()["data"]


def slot(data, court_id, clock):
    starts_at = datetime.fromisoformat(at(clock)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return next(
        item
        for item in data["slots"]
        if item["court_id"] == court_id and item["starts_at"] == starts_at
    )


def test_day_has_hourly_slots_in_club_time(agenda):
    client, court, users, _, _ = agenda
    data = schedule(client, users["bruno"])
    assert data["date"] == DAY
    assert [item["id"] for item in data["courts"]] == [court["id"]]
    times = [item["starts_at"] for item in data["slots"]]
    # 07:00 a 21:00 em São Paulo (UTC-3), 15 blocos de 1 hora.
    assert times[0] == "2030-01-10T10:00:00Z"
    assert times[-1] == "2030-01-11T00:00:00Z"
    assert len(times) == 15
    assert {item["status"] for item in data["slots"]} == {"free"}


def test_slot_status_depends_on_who_asks(agenda):
    client, court, users, ids, book = agenda
    booking = book(users["bruno"], "19:00", 90, player_ids=[ids["carla"]]).json()["data"]
    queued = book(users["admin"], "19:00", join_waitlist=True).json()["data"]
    maintenance(client, users["admin"], court["id"], "08:00", "10:00")

    for viewer in ("bruno", "carla"):
        own = slot(schedule(client, users[viewer]), court["id"], "19:00")
        assert (own["status"], own["booking_id"]) == ("mine", booking["id"])
    # 19:00–20:30 também ocupa o bloco das 20:00.
    assert slot(schedule(client, users["bruno"]), court["id"], "20:00")["status"] == "mine"

    seen_by_admin = schedule(client, users["admin"])
    taken = slot(seen_by_admin, court["id"], "19:00")
    assert taken["status"] == "booked"
    assert taken["booking_id"] is None  # não revela a reserva de outra pessoa
    assert (taken["waitlist_size"], taken["waitlist_entry_id"]) == (1, queued["id"])
    assert slot(seen_by_admin, court["id"], "08:00")["status"] == "maintenance"
    assert slot(seen_by_admin, court["id"], "09:00")["status"] == "maintenance"
    assert slot(seen_by_admin, court["id"], "10:00")["status"] == "free"
    assert slot(schedule(client, users["bruno"]), court["id"], "19:00")["waitlist_entry_id"] is None


def test_schedule_validates_the_date_and_requires_login(agenda):
    client, _, users, _, _ = agenda
    assert client.get("/api/v1/schedule?date=10/01/2030", headers=users["bruno"]).status_code == 422
    assert client.get("/api/v1/schedule", headers=users["bruno"]).status_code == 422
    assert client.get(f"/api/v1/schedule?date={DAY}").status_code == 401


def test_player_search_excludes_self(agenda):
    client, _, users, ids, _ = agenda
    found = client.get("/api/v1/players?q=ar", headers=users["carla"]).json()["data"]
    # "Maria Silva" (admin) contém "ar"; Carla não aparece para si mesma.
    assert found == [{"id": ids["admin"], "name": "Maria Silva"}]
    assert client.get("/api/v1/players?q=a", headers=users["carla"]).status_code == 422


def test_guests_confirm_attendance_and_rescheduling_resets_it(agenda):
    client, _, users, ids, book = agenda
    booking = book(users["bruno"], "19:00", player_ids=[ids["carla"]]).json()["data"]
    attendance = {player["id"]: player["attendance"] for player in booking["players"]}
    assert attendance == {ids["bruno"]: "confirmed", ids["carla"]: "pending"}
    assert booking["my_role"] == "organizer"

    path = f"/api/v1/bookings/{booking['id']}"
    answered = client.put(
        f"{path}/attendance", headers=users["carla"], json={"response": "confirmed"}
    )
    assert answered.status_code == 200
    assert answered.json()["data"]["my_role"] == "participant"
    assert {p["id"]: p["attendance"] for p in answered.json()["data"]["players"]}[ids["carla"]] == (
        "confirmed"
    )

    organizer = client.put(
        f"{path}/attendance", headers=users["bruno"], json={"response": "declined"}
    )
    assert organizer.status_code == 403
    assert organizer.json()["message"] == "Quem organiza já está confirmado."
    stranger = account(client, "Davi", "davi@example.com")
    assert (
        client.put(
            f"{path}/attendance", headers=stranger, json={"response": "declined"}
        ).status_code
        == 404
    )
    bad = client.put(f"{path}/attendance", headers=users["carla"], json={"response": "talvez"})
    assert bad.status_code == 422

    # Trocar só os jogadores mantém a resposta de quem continua.
    kept = client.patch(
        path, headers=users["bruno"], json={"player_ids": [ids["carla"], ids["admin"]]}
    )
    players = {p["id"]: p["attendance"] for p in kept.json()["data"]["players"]}
    assert players == {
        ids["bruno"]: "confirmed",
        ids["carla"]: "confirmed",
        ids["admin"]: "pending",
    }

    moved = client.patch(path, headers=users["bruno"], json={"starts_at": at("21:00")})
    players = {p["id"]: p["attendance"] for p in moved.json()["data"]["players"]}
    assert players == {ids["bruno"]: "confirmed", ids["carla"]: "pending", ids["admin"]: "pending"}


def test_reschedule_to_another_court_promotes_the_old_queue(agenda):
    client, court, users, ids, book = agenda
    other = client.post(
        "/api/v1/courts",
        headers=users["admin"],
        json={**COURT, "name": "Quadra 2", "max_players": 2},
    ).json()["data"]
    taken = book(users["bruno"], "19:00", player_ids=[ids["carla"]]).json()["data"]
    waiting = book(users["admin"], "19:00", join_waitlist=True).json()["data"]

    moved = client.patch(
        f"/api/v1/bookings/{taken['id']}", headers=users["bruno"], json={"court_id": other["id"]}
    )
    assert moved.status_code == 200
    assert moved.json()["data"]["court"]["id"] == other["id"]
    assert (
        client.get(f"/api/v1/bookings/{waiting['id']}", headers=users["admin"]).json()["data"][
            "status"
        ]
        == "confirmed"
    )

    # A quadra de destino precisa comportar os jogadores atuais.
    crowded = book(users["carla"], "21:00", player_ids=[ids["admin"], ids["bruno"]]).json()["data"]
    refused = client.patch(
        f"/api/v1/bookings/{crowded['id']}", headers=users["carla"], json={"court_id": other["id"]}
    )
    assert refused.status_code == 422
    assert "até 2 jogadores" in refused.json()["errors"]["player_ids"][0]
    missing = client.patch(
        f"/api/v1/bookings/{crowded['id']}", headers=users["carla"], json={"court_id": 999999}
    )
    assert missing.status_code == 404
    assert court["id"] != other["id"]


def test_scopes_split_upcoming_and_history(agenda, db_session):
    client, court, users, ids, book = agenda
    upcoming = book(users["bruno"], "19:00").json()["data"]
    cancelled = book(users["bruno"], "21:00").json()["data"]
    client.post(f"/api/v1/bookings/{cancelled['id']}/cancel", headers=users["bruno"])
    queued = book(users["carla"], "19:00", join_waitlist=True).json()["data"]
    ended_at = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=3)
    finished = BookingModel(
        court_id=court["id"],
        user_id=ids["bruno"],
        starts_at=ended_at,
        ends_at=ended_at + timedelta(hours=1),
        status="confirmed",
    )
    db_session.add(finished)
    db_session.commit()

    def ids_for(headers, query):
        response = client.get(f"/api/v1/bookings?{query}", headers=headers).json()
        return [item["id"] for item in response["data"]]

    assert ids_for(users["bruno"], "scope=upcoming") == [upcoming["id"]]
    # Histórico: mais recente primeiro.
    assert ids_for(users["bruno"], "scope=past") == [cancelled["id"], finished.id]
    assert queued["id"] not in ids_for(users["carla"], "scope=upcoming")
    assert ids_for(users["carla"], "status=waitlisted") == [queued["id"]]

    mine = book(users["admin"], "08:00").json()["data"]
    assert len(ids_for(users["admin"], "scope=upcoming")) == 2
    assert ids_for(users["admin"], "scope=upcoming&only_mine=true") == [mine["id"]]
