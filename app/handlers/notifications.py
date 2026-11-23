"""Avisos por e-mail sobre reservas (US15-US18).

As mensagens são montadas durante a requisição, com os dados já gravados; o envio em si
acontece depois da resposta (ver app/core/mailer.py).

- US16: reserva confirmada (na hora do pedido ou quando a fila libera a vaga - US15).
- US17: reserva cancelada ou alterada (remarcação, manutenção ou exclusão), e convite.
- US18: lembrete antes do horário, enviado uma única vez por horário.
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.config import Settings
from app.core.mailer import Email
from app.domain.entities import Attendance, Booking, BookingStatus, Contact, User
from app.handlers.bookings import utcnow
from app.repositories.contracts import BookingRepository

WEEKDAYS = (
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
)
SIGNATURE = "\n\n—\nClube de Tênis\nEste é um aviso automático; não é preciso responder."


class BookingNotifier:
    def __init__(self, bookings: BookingRepository, settings: Settings) -> None:
        self.bookings = bookings
        self.zone = ZoneInfo(settings.club_timezone)
        self.app_url = settings.app_url.rstrip("/")

    # ---------- Formatação ----------

    def when(self, booking: Booking) -> str:
        starts = booking.starts_at.astimezone(self.zone)
        ends = booking.ends_at.astimezone(self.zone)
        return (
            f"{WEEKDAYS[starts.weekday()]}, {starts:%d/%m/%Y}, das {starts:%H:%M} às {ends:%H:%M}"
        )

    def link(self, booking: Booking) -> str:
        return f"{self.app_url}/#/reservas/{booking.id}"

    def details(self, booking: Booking) -> str:
        return (
            f"Quadra: {booking.court.name}\n"
            f"Horário: {self.when(booking)}\n"
            f"Organizador: {booking.organizer.name}\n\n"
            f"Detalhes da reserva: {self.link(booking)}"
        )

    def _emails(
        self,
        booking: Booking,
        user_ids: Iterable[int],
        subject: str,
        intro: Callable[[Contact], str],
    ) -> list[Email]:
        contacts = self.bookings.contacts(set(user_ids))
        return [
            Email(
                to=contact.email,
                subject=f"{subject} — {booking.court.name}",
                text=(
                    f"Olá, {contact.name}.\n\n{intro(contact)}\n\n"
                    f"{self.details(booking)}{SIGNATURE}"
                ),
            )
            for contact in sorted(contacts.values(), key=lambda item: item.id)
        ]

    # ---------- Eventos ----------

    def created(self, booking: Booking) -> list[Email]:
        """Pedido novo: confirmação para quem reservou (US16) e convite para os jogadores."""
        emails: list[Email] = []
        if booking.status is BookingStatus.CONFIRMED:
            emails += self._emails(
                booking,
                [booking.organizer.id],
                "Reserva confirmada",
                lambda _: "Sua reserva foi confirmada.",
            )
            emails += self.invited(booking, [player.id for player in booking.players])
        return emails

    def invited(self, booking: Booking, user_ids: Iterable[int]) -> list[Email]:
        guests = [item for item in user_ids if item != booking.organizer.id]
        if booking.status is not BookingStatus.CONFIRMED or not guests:
            return []
        return self._emails(
            booking,
            guests,
            "Convite para partida",
            lambda _: (
                f"{booking.organizer.name} convidou você para uma partida. "
                "Confirme ou recuse sua presença pelo link abaixo."
            ),
        )

    def promoted(self, booking_ids: Sequence[int]) -> list[Email]:
        """US15/US16: a vaga liberada foi confirmada para o próximo da fila."""
        emails: list[Email] = []
        for booking_id in booking_ids:
            booking = self.bookings.get(booking_id)
            if booking is None or booking.status is not BookingStatus.CONFIRMED:
                continue
            emails += self._emails(
                booking,
                [booking.organizer.id],
                "Reserva confirmada",
                lambda _: (
                    "O horário que você aguardava na fila de espera foi liberado, "
                    "e sua reserva foi confirmada."
                ),
            )
            emails += self.invited(booking, [player.id for player in booking.players])
        return emails

    def _involved_except(self, booking: Booking, actor: User) -> list[int]:
        ids = {booking.organizer.id, *(player.id for player in booking.players)}
        return sorted(ids - {actor.id})

    def cancelled(self, booking: Booking, actor: User, *, reason: str | None = None) -> list[Email]:
        """US17: cancelamento avisa todos os envolvidos, menos quem cancelou."""
        if booking.status is BookingStatus.WAITLISTED:
            return []  # Sair da fila não afeta mais ninguém.
        if reason:
            message = f"A reserva abaixo foi cancelada. Motivo: {reason}."
        elif actor.id == booking.organizer.id:
            message = f"{booking.organizer.name} cancelou a reserva abaixo."
        else:
            message = "A reserva abaixo foi cancelada pela administração do clube."
        return self._emails(
            booking, self._involved_except(booking, actor), "Reserva cancelada", lambda _: message
        )

    def rescheduled(self, booking: Booking, actor: User) -> list[Email]:
        """US17: remarcação avisa os envolvidos, que precisam confirmar o novo horário."""
        if booking.status is not BookingStatus.CONFIRMED:
            message = (
                "A reserva abaixo foi alterada para um horário ocupado e está na fila de espera. "
                "Você será avisado se a vaga for confirmada."
            )
        elif actor.id == booking.organizer.id:
            message = (
                f"{booking.organizer.name} alterou a reserva abaixo. "
                "Confirme sua presença no novo horário."
            )
        else:
            message = "A administração do clube alterou a reserva abaixo."
        return self._emails(
            booking, self._involved_except(booking, actor), "Reserva alterada", lambda _: message
        )


@dataclass(frozen=True, slots=True)
class ReminderRun:
    bookings: int
    emails: list[Email]


class SendRemindersHandler:
    """US18: lembra os jogadores das reservas confirmadas que começam em breve.

    Chamado periodicamente (rota interna). Cada reserva recebe um único lembrete; remarcar
    zera o registro. Jogadores que recusaram a presença não recebem.
    """

    def __init__(
        self,
        bookings: BookingRepository,
        settings: Settings,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.bookings = bookings
        self.notifier = BookingNotifier(bookings, settings)
        self.lead = timedelta(hours=settings.reminder_hours_before)
        self.clock = clock

    def handle(self) -> ReminderRun:
        now = self.clock()
        emails: list[Email] = []
        with self.bookings.transaction():
            due = self.bookings.due_for_reminder(now, now + self.lead)
            for booking_id in due:
                booking = self.bookings.get(booking_id)
                if booking is None:
                    continue
                going = [
                    player.id
                    for player in booking.players
                    if player.attendance is not Attendance.DECLINED
                ]
                emails += self.notifier._emails(
                    booking,
                    {booking.organizer.id, *going},
                    "Lembrete de partida",
                    lambda _, b=booking: f"Sua partida está chegando: {self.notifier.when(b)}.",
                )
            self.bookings.mark_reminded(due, now)
        return ReminderRun(bookings=len(due), emails=emails)
