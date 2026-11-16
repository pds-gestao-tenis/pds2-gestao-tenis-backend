from dataclasses import dataclass, field
from datetime import datetime

from app.domain.entities import BookingScope, BookingStatus


@dataclass(frozen=True, slots=True)
class CreateBookingData:
    court_id: int
    starts_at: datetime
    duration_minutes: int
    player_ids: tuple[int, ...] = ()
    join_waitlist: bool = False


@dataclass(frozen=True, slots=True)
class UpdateBookingData:
    """Campos ausentes (None) mantêm o valor atual."""

    court_id: int | None = None
    starts_at: datetime | None = None
    duration_minutes: int | None = None
    player_ids: tuple[int, ...] | None = None
    join_waitlist: bool = False


@dataclass(frozen=True, slots=True)
class NewBookingData:
    court_id: int
    user_id: int
    starts_at: datetime
    ends_at: datetime
    status: BookingStatus
    player_ids: tuple[int, ...] = field(default=())


@dataclass(frozen=True, slots=True)
class BookingFilters:
    court_id: int | None = None
    status: BookingStatus | None = None
    starts_from: datetime | None = None
    starts_to: datetime | None = None
    scope: BookingScope | None = None
    # None lista todas (admin); um id restringe às reservas em que a conta organiza ou joga.
    visible_to: int | None = None
    # Referência para scope ("já terminou?"); preenchida pelo handler.
    now: datetime | None = None
