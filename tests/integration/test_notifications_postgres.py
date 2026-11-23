"""US15-US18: avisos por e-mail sobre reservas."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr

from app.dependencies import get_mailer
from tests.integration.conftest import at, maintenance

pytestmark = pytest.mark.integration


class FakeMailer:
    def __init__(self) -> None:
        self.sent = []

    def send(self, email) -> None:
        self.sent.append(email)

    def to(self, address):
        return [email for email in self.sent if email.to == address]

    def subjects(self):
        return sorted((email.to, email.subject.split(" — ")[0]) for email in self.sent)


@pytest.fixture
def mail(agenda):
    client = agenda[0]
    fake = FakeMailer()
    client.app.dependency_overrides[get_mailer] = lambda: fake
    return fake


def test_confirmed_booking_emails_organizer_and_invites_players(agenda, mail):
    _, court, users, ids, book = agenda
    booking = book(users["bruno"], "19:00", player_ids=[ids["carla"]]).json()["data"]

    assert mail.subjects() == [
        ("bruno@example.com", "Reserva confirmada"),
        ("carla@example.com", "Convite para partida"),
    ]
    confirmation = mail.to("bruno@example.com")[0]
    assert confirmation.subject == f"Reserva confirmada — {court['name']}"
    assert "Olá, Bruno." in confirmation.text
    assert "quinta-feira, 10/01/2030, das 19:00 às 20:00" in confirmation.text
    assert f"/#/reservas/{booking['id']}" in confirmation.text
    assert "Bruno convidou você" in mail.to("carla@example.com")[0].text


def test_waitlisted_request_sends_nothing_until_the_slot_frees(agenda, mail):
    client, _, users, _, book = agenda
    first = book(users["admin"], "19:00").json()["data"]
    book(users["bruno"], "19:00", join_waitlist=True)
    assert mail.to("bruno@example.com") == []

    mail.sent.clear()
    client.post(f"/api/v1/bookings/{first['id']}/cancel", headers=users["admin"])
    # US15/US16: a vaga foi oferecida (confirmada) ao próximo da fila, que é avisado.
    assert mail.subjects() == [("bruno@example.com", "Reserva confirmada")]
    assert "fila de espera foi liberado" in mail.sent[0].text


def test_cancellation_emails_everyone_but_who_cancelled(agenda, mail):
    client, _, users, ids, book = agenda
    booking = book(users["bruno"], "19:00", player_ids=[ids["carla"], ids["admin"]]).json()["data"]
    mail.sent.clear()

    client.post(f"/api/v1/bookings/{booking['id']}/cancel", headers=users["bruno"])
    assert mail.subjects() == [
        ("carla@example.com", "Reserva cancelada"),
        ("maria@example.com", "Reserva cancelada"),
    ]
    assert "Bruno cancelou a reserva" in mail.sent[0].text


def test_admin_cancellation_and_leaving_the_queue(agenda, mail):
    client, _, users, _, book = agenda
    booking = book(users["bruno"], "19:00").json()["data"]
    queued = book(users["carla"], "19:00", join_waitlist=True).json()["data"]
    mail.sent.clear()

    # Sair da fila não avisa ninguém.
    client.post(f"/api/v1/bookings/{queued['id']}/cancel", headers=users["carla"])
    assert mail.sent == []

    client.post(f"/api/v1/bookings/{booking['id']}/cancel", headers=users["admin"])
    assert mail.subjects() == [("bruno@example.com", "Reserva cancelada")]
    assert "pela administração do clube" in mail.sent[0].text


def test_reschedule_and_new_players_are_notified(agenda, mail):
    client, _, users, ids, book = agenda
    booking = book(users["bruno"], "19:00", player_ids=[ids["carla"]]).json()["data"]
    mail.sent.clear()

    moved = client.patch(
        f"/api/v1/bookings/{booking['id']}", headers=users["bruno"], json={"starts_at": at("20:00")}
    )
    assert moved.status_code == 200
    assert mail.subjects() == [("carla@example.com", "Reserva alterada")]
    assert "das 20:00 às 21:00" in mail.sent[0].text

    mail.sent.clear()
    client.patch(
        f"/api/v1/bookings/{booking['id']}",
        headers=users["bruno"],
        json={"player_ids": [ids["carla"], ids["admin"]]},
    )
    # Só quem entrou agora recebe o convite.
    assert mail.subjects() == [("maria@example.com", "Convite para partida")]


def test_maintenance_cancellation_is_explained(agenda, mail):
    client, court, users, ids, book = agenda
    book(users["bruno"], "19:00", player_ids=[ids["carla"]])
    mail.sent.clear()

    response = maintenance(
        client, users["admin"], court["id"], "18:00", "21:00", cancel_bookings=True
    )
    assert response.status_code == 201
    assert mail.subjects() == [
        ("bruno@example.com", "Reserva cancelada"),
        ("carla@example.com", "Reserva cancelada"),
    ]
    assert "período bloqueado na quadra (Troca do saibro)" in mail.sent[0].text


def test_admin_delete_notifies_players(agenda, mail):
    client, _, users, _, book = agenda
    booking = book(users["bruno"], "19:00").json()["data"]
    mail.sent.clear()
    assert (
        client.delete(f"/api/v1/bookings/{booking['id']}", headers=users["admin"]).status_code
        == 204
    )
    assert mail.subjects() == [("bruno@example.com", "Reserva cancelada")]


# ---------- US18: lembretes ----------


def soon(hours: int) -> str:
    start = (datetime.now(UTC) + timedelta(hours=hours)).replace(minute=0, second=0, microsecond=0)
    return start.isoformat()


@pytest.fixture
def cron(agenda):
    client = agenda[0]
    client.app.state.settings.cron_token = SecretStr("segredo-do-agendador")
    return lambda token="segredo-do-agendador": client.post(
        "/api/v1/internal/reminders", headers={"X-Cron-Token": token} if token else {}
    )


def booking_at(client, headers, court_id, starts_at, **extra):
    response = client.post(
        "/api/v1/bookings",
        headers=headers,
        json={"court_id": court_id, "starts_at": starts_at, "duration_minutes": 60, **extra},
    )
    assert response.status_code == 201, response.json()
    return response.json()["data"]


def test_reminders_require_the_cron_token(agenda, cron):
    assert cron(token=None).status_code == 401
    assert cron(token="errado").status_code == 401
    assert cron().status_code == 200


def test_reminders_without_configured_token_are_refused(agenda):
    client = agenda[0]
    client.app.state.settings.cron_token = None
    response = client.post("/api/v1/internal/reminders", headers={"X-Cron-Token": "x"})
    assert response.status_code == 401


def test_reminder_is_sent_once_to_players_going(agenda, mail, cron):
    client, court, users, ids, _ = agenda
    near = booking_at(
        client, users["bruno"], court["id"], soon(3), player_ids=[ids["carla"], ids["admin"]]
    )
    booking_at(client, users["carla"], court["id"], soon(30))  # fora da janela de 24 h
    client.put(
        f"/api/v1/bookings/{near['id']}/attendance",
        headers=users["admin"],
        json={"response": "declined"},
    )
    mail.sent.clear()

    first = cron()
    assert first.json() == {"data": {"reminded_bookings": 1, "emails": 2}}
    assert mail.subjects() == [
        ("bruno@example.com", "Lembrete de partida"),
        ("carla@example.com", "Lembrete de partida"),
    ]

    mail.sent.clear()
    assert cron().json() == {"data": {"reminded_bookings": 0, "emails": 0}}
    assert mail.sent == []


def test_rescheduling_rearms_the_reminder_and_cancelled_ones_are_skipped(agenda, mail, cron):
    client, court, users, _, _ = agenda
    kept = booking_at(client, users["bruno"], court["id"], soon(2))
    dropped = booking_at(client, users["carla"], court["id"], soon(4))
    client.post(f"/api/v1/bookings/{dropped['id']}/cancel", headers=users["carla"])
    cron()

    client.patch(
        f"/api/v1/bookings/{kept['id']}", headers=users["bruno"], json={"starts_at": soon(5)}
    )
    mail.sent.clear()
    assert cron().json()["data"]["reminded_bookings"] == 1
    assert mail.subjects() == [("bruno@example.com", "Lembrete de partida")]


def test_mail_failure_does_not_break_the_request(agenda):
    client, _, users, _, book = agenda

    class Broken:
        def send(self, email):
            raise OSError("Resend fora do ar")

    client.app.dependency_overrides[get_mailer] = lambda: Broken()
    assert book(users["bruno"], "19:00").status_code == 201
