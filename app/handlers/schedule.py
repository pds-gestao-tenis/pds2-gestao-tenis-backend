"""Agenda de um dia: cada quadra em blocos de 1 hora, como a grade do frontend mostra.

O estado de cada bloco é visto pela conta que pede, nesta prioridade:
manutenção > reserva própria ("mine") > ocupado por outra pessoa ("booked") > livre.
Reservas de 90 minutos ou que começam na meia hora ocupam todos os blocos que tocam.
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.domain.entities import (
    BookingStatus,
    Person,
    Schedule,
    ScheduleSlot,
    SlotStatus,
    User,
)
from app.repositories.contracts import BookingRepository, CourtRepository, UserRepository

FIRST_HOUR = 7
LAST_HOUR = 21  # último bloco começa às 21:00 e termina às 22:00
SLOT = timedelta(hours=1)


class GetScheduleHandler:
    def __init__(
        self, courts: CourtRepository, bookings: BookingRepository, timezone: ZoneInfo
    ) -> None:
        self.courts = courts
        self.bookings = bookings
        self.timezone = timezone

    def handle(self, user: User, day: date) -> Schedule:
        starts = [
            datetime.combine(day, time(hour), tzinfo=self.timezone).astimezone(UTC)
            for hour in range(FIRST_HOUR, LAST_HOUR + 1)
        ]
        courts = self.courts.all()
        day_bookings = self.bookings.day_bookings(starts[0], starts[-1] + SLOT)
        slots = []
        for court in courts:
            court_bookings = [item for item in day_bookings if item.court_id == court.id]
            for start in starts:
                end = start + SLOT
                touching = [
                    item for item in court_bookings if item.starts_at < end and item.ends_at > start
                ]
                confirmed = [item for item in touching if item.status is BookingStatus.CONFIRMED]
                queue = [item for item in touching if item.status is BookingStatus.WAITLISTED]
                mine = next(
                    (
                        item
                        for item in confirmed
                        if item.organizer_id == user.id or user.id in item.player_ids
                    ),
                    None,
                )
                own_entry = next((item for item in queue if item.organizer_id == user.id), None)
                if any(
                    window.starts_at < end and window.ends_at > start
                    for window in court.maintenance
                ):
                    status = SlotStatus.MAINTENANCE
                elif mine is not None:
                    status = SlotStatus.MINE
                elif confirmed:
                    status = SlotStatus.BOOKED
                else:
                    status = SlotStatus.FREE
                slots.append(
                    ScheduleSlot(
                        court_id=court.id,
                        starts_at=start,
                        ends_at=end,
                        status=status,
                        booking_id=mine.id if status is SlotStatus.MINE else None,
                        waitlist_size=len(queue),
                        waitlist_entry_id=own_entry.id if own_entry else None,
                    )
                )
        return Schedule(day, courts, tuple(slots))


class SearchPlayersHandler:
    """Contas para convidar a uma partida (a própria fica de fora)."""

    LIMIT = 10

    def __init__(self, users: UserRepository) -> None:
        self.users = users

    def handle(self, user: User, term: str) -> Sequence[Person]:
        return self.users.search(term.strip(), exclude_id=user.id, limit=self.LIMIT)
