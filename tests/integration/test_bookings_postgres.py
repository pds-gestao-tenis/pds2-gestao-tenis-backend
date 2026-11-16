from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import BookingModel
from tests.integration.conftest import at, maintenance
from tests.integration.test_courts_postgres import account

pytestmark = pytest.mark.integration


def status_of(client, headers, booking_id):
    return client.get(f"/api/v1/bookings/{booking_id}", headers=headers).json()["data"]


def test_free_slot_is_confirmed_with_organizer_among_players(agenda):
    client, court, users, ids, book = agenda
    response = book(users["bruno"], "19:00", 90, player_ids=[ids["carla"]])
    assert response.status_code == 201
    booking = response.json()["data"]
    assert booking["status"] == "confirmed"
    assert booking["duration_minutes"] == 90
    assert booking["starts_at"] == "2030-01-10T22:00:00Z"
    assert booking["ends_at"] == "2030-01-10T23:30:00Z"
    assert booking["court"] == {"id": court["id"], "name": court["name"]}
    assert booking["organizer"]["id"] == ids["bruno"]
    assert [player["id"] for player in booking["players"]] == [ids["bruno"], ids["carla"]]
    assert booking["waitlist_position"] is None
    assert booking["requested_at"]


def test_taken_slot_needs_join_waitlist_and_queue_keeps_order(agenda):
    client, _, users, _, book = agenda
    first = book(users["admin"], "19:00").json()["data"]

    refused = book(users["bruno"], "19:00")
    assert refused.status_code == 409
    assert refused.json()["message"] == "Esse horário já está reservado."

    bruno = book(users["bruno"], "19:00", join_waitlist=True).json()["data"]
    carla = book(users["carla"], "19:00", join_waitlist=True).json()["data"]
    assert (bruno["status"], bruno["waitlist_position"]) == ("waitlisted", 1)
    assert (carla["status"], carla["waitlist_position"]) == ("waitlisted", 2)

    cancelled = client.post(f"/api/v1/bookings/{first['id']}/cancel", headers=users["admin"])
    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["status"] == "cancelled"
    assert cancelled.json()["data"]["cancelled_at"]

    # O primeiro a pedir fica com o horário; a segunda sobe na fila.
    assert status_of(client, users["bruno"], bruno["id"])["status"] == "confirmed"
    carla_now = status_of(client, users["carla"], carla["id"])
    assert (carla_now["status"], carla_now["waitlist_position"]) == ("waitlisted", 1)


def test_queue_promotes_in_request_order_even_with_partial_overlaps(agenda):
    client, _, users, _, book = agenda
    taken = book(users["admin"], "19:00", 90).json()["data"]  # 19:00–20:30
    bruno = book(users["bruno"], "19:30", join_waitlist=True).json()["data"]  # 19:30–20:30
    carla = book(users["carla"], "19:00", join_waitlist=True).json()["data"]  # 19:00–20:00
    client.post(f"/api/v1/bookings/{taken['id']}/cancel", headers=users["admin"])
    # Bruno pediu antes; o horário de Carla se sobrepõe ao dele, então ela continua na fila.
    assert status_of(client, users["bruno"], bruno["id"])["status"] == "confirmed"
    assert status_of(client, users["carla"], carla["id"])["status"] == "waitlisted"


def test_leaving_the_queue_does_not_promote_anyone(agenda):
    client, _, users, _, book = agenda
    book(users["admin"], "19:00")
    bruno = book(users["bruno"], "19:00", join_waitlist=True).json()["data"]
    carla = book(users["carla"], "19:00", join_waitlist=True).json()["data"]
    client.post(f"/api/v1/bookings/{bruno['id']}/cancel", headers=users["bruno"])
    carla_now = status_of(client, users["carla"], carla["id"])
    assert (carla_now["status"], carla_now["waitlist_position"]) == ("waitlisted", 1)


def test_adjacent_slots_do_not_conflict(agenda):
    _, _, users, _, book = agenda
    assert book(users["admin"], "19:00").json()["data"]["status"] == "confirmed"
    assert book(users["bruno"], "20:00").json()["data"]["status"] == "confirmed"
    assert book(users["carla"], "18:00").json()["data"]["status"] == "confirmed"


@pytest.mark.parametrize(
    ("start", "duration", "field"),
    [
        ("19:15", 60, "starts_at"),
        ("19:00", 45, "duration_minutes"),
        ("19:00", 120, "duration_minutes"),
    ],
)
def test_rejects_invalid_times(agenda, start, duration, field):
    _, _, users, _, book = agenda
    response = book(users["bruno"], start, duration)
    assert response.status_code == 422
    assert field in response.json()["errors"]


def test_rejects_past_times_unknown_players_and_too_many_players(agenda):
    client, court, users, ids, book = agenda
    past = client.post(
        "/api/v1/bookings",
        headers=users["bruno"],
        json={"court_id": court["id"], "starts_at": "2020-01-10T19:00:00-03:00"},
    )
    assert past.status_code == 422
    assert past.json()["errors"] == {"starts_at": ["Escolha um horário futuro."]}

    unknown = book(users["bruno"], "19:00", player_ids=[999999])
    assert unknown.status_code == 422
    assert unknown.json()["errors"]["player_ids"] == ["Jogadores não encontrados: 999999."]

    client.patch(f"/api/v1/courts/{court['id']}", headers=users["admin"], json={"max_players": 2})
    crowded = book(users["bruno"], "19:00", player_ids=[ids["carla"], ids["admin"]])
    assert crowded.status_code == 422
    assert "até 2 jogadores" in crowded.json()["errors"]["player_ids"][0]
    assert book(users["bruno"], "19:00", player_ids=[ids["carla"], ids["bruno"]]).status_code == 201

    missing_court = client.post(
        "/api/v1/bookings",
        headers=users["bruno"],
        json={"court_id": 999999, "starts_at": at("19:00")},
    )
    assert missing_court.status_code == 404


def test_same_account_cannot_queue_twice_for_the_same_time(agenda):
    _, _, users, _, book = agenda
    book(users["admin"], "19:00")
    assert book(users["bruno"], "19:00", join_waitlist=True).status_code == 201
    again = book(users["bruno"], "19:30", join_waitlist=True)
    assert again.status_code == 409
    assert "sobrepõe" in again.json()["message"]


def test_visibility_and_permissions(agenda):
    client, _, users, ids, book = agenda
    booking = book(users["bruno"], "19:00", player_ids=[ids["carla"]]).json()["data"]
    path = f"/api/v1/bookings/{booking['id']}"
    stranger = account(client, "Davi", "davi@example.com")

    assert client.get(path, headers=stranger).status_code == 404
    assert client.get(path, headers=users["carla"]).status_code == 200
    assert client.get(path, headers=users["admin"]).status_code == 200
    # Quem só joga vê a reserva, mas não altera.
    assert client.post(f"{path}/cancel", headers=users["carla"]).status_code == 403
    assert client.post(f"{path}/cancel", headers=stranger).status_code == 404
    assert client.delete(path, headers=users["bruno"]).status_code == 403

    assert client.post(f"{path}/cancel", headers=users["bruno"]).status_code == 200
    again = client.post(f"{path}/cancel", headers=users["bruno"])
    assert again.status_code == 409
    assert again.json()["message"] == "Esta reserva já foi cancelada."


def test_listing_shows_own_bookings_and_admin_sees_all(agenda):
    client, court, users, ids, book = agenda
    book(users["bruno"], "19:00", player_ids=[ids["carla"]])
    book(users["admin"], "21:00")
    book(users["carla"], "21:00", join_waitlist=True)

    def listing(headers, query=""):
        return client.get(f"/api/v1/bookings{query}", headers=headers).json()

    assert listing(users["bruno"])["meta"]["total"] == 1
    assert listing(users["carla"])["meta"]["total"] == 2  # joga na do Bruno e está na fila
    assert listing(users["admin"])["meta"]["total"] == 3
    waitlisted = listing(users["admin"], "?status=waitlisted")
    assert [item["organizer"]["id"] for item in waitlisted["data"]] == [ids["carla"]]
    window = listing(
        users["admin"],
        f"?court_id={court['id']}&starts_from=2030-01-10T23:00:00Z&starts_to=2030-01-11T01:00:00Z",
    )
    assert window["meta"]["total"] == 2


def test_reschedule_frees_the_old_slot_for_the_queue(agenda):
    client, _, users, ids, book = agenda
    taken = book(users["admin"], "19:00").json()["data"]
    bruno = book(users["bruno"], "19:00", join_waitlist=True).json()["data"]

    moved = client.patch(
        f"/api/v1/bookings/{taken['id']}",
        headers=users["admin"],
        json={"starts_at": at("21:00"), "duration_minutes": 90, "player_ids": [ids["carla"]]},
    )
    assert moved.status_code == 200
    data = moved.json()["data"]
    assert (data["status"], data["duration_minutes"]) == ("confirmed", 90)
    assert {player["id"] for player in data["players"]} == {ids["admin"], ids["carla"]}
    assert status_of(client, users["bruno"], bruno["id"])["status"] == "confirmed"

    # Remarcar para um horário ocupado exige join_waitlist, como um pedido novo.
    blocked = client.patch(
        f"/api/v1/bookings/{bruno['id']}", headers=users["bruno"], json={"starts_at": at("21:30")}
    )
    assert blocked.status_code == 409


def test_admin_delete_promotes_the_queue(agenda):
    client, _, users, _, book = agenda
    taken = book(users["bruno"], "19:00").json()["data"]
    carla = book(users["carla"], "19:00", join_waitlist=True).json()["data"]
    assert (
        client.delete(f"/api/v1/bookings/{taken['id']}", headers=users["admin"]).status_code == 204
    )
    assert client.get(f"/api/v1/bookings/{taken['id']}", headers=users["admin"]).status_code == 404
    assert status_of(client, users["carla"], carla["id"])["status"] == "confirmed"


def test_started_booking_cannot_be_changed(agenda, db_session):
    client, court, users, ids, _ = agenda
    started = datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(minutes=10)
    record = BookingModel(
        court_id=court["id"],
        user_id=ids["bruno"],
        starts_at=started,
        ends_at=started + timedelta(hours=1),
        status="confirmed",
    )
    db_session.add(record)
    db_session.commit()
    response = client.post(f"/api/v1/bookings/{record.id}/cancel", headers=users["bruno"])
    assert response.status_code == 409
    assert response.json()["message"] == "Reservas que já começaram não podem ser alteradas."


def test_court_with_upcoming_bookings_cannot_be_deleted(agenda):
    client, court, users, _, book = agenda
    booking = book(users["bruno"], "19:00").json()["data"]
    path = f"/api/v1/courts/{court['id']}"
    assert client.delete(path, headers=users["admin"]).status_code == 409
    client.post(f"/api/v1/bookings/{booking['id']}/cancel", headers=users["bruno"])
    assert client.delete(path, headers=users["admin"]).status_code == 204


def test_database_blocks_overlapping_confirmed_bookings(agenda, db_session):
    _, court, _, ids, _ = agenda
    start = datetime(2030, 1, 10, 22, tzinfo=UTC)
    for offset in (0, 30):
        db_session.add(
            BookingModel(
                court_id=court["id"],
                user_id=ids["bruno"],
                starts_at=start + timedelta(minutes=offset),
                ends_at=start + timedelta(minutes=offset + 60),
                status="confirmed",
            )
        )
    with pytest.raises(IntegrityError) as error:
        db_session.flush()
    assert error.value.orig.sqlstate == "23P01"
    db_session.rollback()


def test_maintenance_lifecycle_blocks_bookings(agenda):
    client, court, users, _, book = agenda
    added = maintenance(client, users["admin"], court["id"], "08:00", "12:00")
    assert added.status_code == 201
    windows = added.json()["data"]["maintenance"]
    assert len(windows) == 1
    assert windows[0]["reason"] == "Troca do saibro"
    assert windows[0]["starts_at"] == "2030-01-10T11:00:00Z"
    # A quadra consultada por qualquer conta mostra a manutenção.
    path = f"/api/v1/courts/{court['id']}"
    assert client.get(path, headers=users["bruno"]).json()["data"]["maintenance"] == windows

    blocked = book(users["bruno"], "11:30")
    assert blocked.status_code == 409
    assert blocked.json()["message"] == "Essa quadra está em manutenção nesse horário."
    assert book(users["bruno"], "11:30", join_waitlist=True).status_code == 409
    assert book(users["bruno"], "12:00").status_code == 201  # termina às 12:00: não conflita

    removed = client.delete(f"{path}/maintenance/{windows[0]['id']}", headers=users["admin"])
    assert removed.status_code == 200
    assert removed.json()["data"]["maintenance"] == []
    assert book(users["carla"], "10:00").status_code == 201
    missing = client.delete(f"{path}/maintenance/{windows[0]['id']}", headers=users["admin"])
    assert missing.status_code == 404


def test_maintenance_over_bookings_needs_cancel_bookings(agenda):
    client, court, users, _, book = agenda
    taken = book(users["admin"], "19:00", 90).json()["data"]  # 19:00–20:30
    waiting = book(users["bruno"], "20:00", join_waitlist=True).json()["data"]  # 20:00–21:00
    outside = book(users["carla"], "18:00", join_waitlist=True)  # 18:00–19:00: livre
    assert outside.json()["data"]["status"] == "confirmed"
    queued = book(users["carla"], "19:00", join_waitlist=True).json()["data"]  # 19:00–20:00

    refused = maintenance(client, users["admin"], court["id"], "20:00", "22:00")
    assert refused.status_code == 409
    assert refused.json()["errors"]["cancel_bookings"][0].startswith("Há 2 reserva(s)")

    accepted = maintenance(
        client, users["admin"], court["id"], "20:00", "22:00", cancel_bookings=True
    )
    assert accepted.status_code == 201
    assert status_of(client, users["admin"], taken["id"])["status"] == "cancelled"
    assert status_of(client, users["bruno"], waiting["id"])["status"] == "cancelled"
    # A confirmada cancelada liberou 19:00–20:00, fora da manutenção: Carla, que esperava, fica.
    assert status_of(client, users["carla"], queued["id"])["status"] == "confirmed"


def test_maintenance_validation_and_permissions(agenda):
    client, court, users, _, _ = agenda
    backwards = maintenance(client, users["admin"], court["id"], "12:00", "08:00")
    assert backwards.status_code == 422
    assert backwards.json()["errors"] == {"ends_at": ["O fim precisa ser depois do início."]}
    past = client.post(
        f"/api/v1/courts/{court['id']}/maintenance",
        headers=users["admin"],
        json={
            "starts_at": "2020-01-01T08:00:00Z",
            "ends_at": "2020-01-01T09:00:00Z",
            "reason": "Antiga",
        },
    )
    assert past.status_code == 422
    assert "ends_at" in past.json()["errors"]
    assert maintenance(client, users["bruno"], court["id"], "08:00", "12:00").status_code == 403
    assert maintenance(client, users["admin"], 999999, "08:00", "12:00").status_code == 404
