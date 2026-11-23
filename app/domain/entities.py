from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class User:
    id: int
    name: str
    email: str
    created_at: datetime
    is_admin: bool = False


@dataclass(frozen=True, slots=True)
class UserCredentials:
    user: User
    password_hash: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    user: User
    token_hash: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class LoginResult:
    user: User
    access_token: str = field(repr=False)
    expires_at: datetime


class MemberStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


@dataclass(frozen=True, slots=True)
class Member:
    id: int
    name: str
    email: str
    phone: str | None
    status: MemberStatus
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class MemberPage:
    items: tuple[Member, ...]
    total: int
    page: int
    page_size: int


class Surface(StrEnum):
    CLAY = "clay"
    HARD = "hard"
    GRASS = "grass"
    SYNTHETIC = "synthetic"


@dataclass(frozen=True, slots=True)
class MaintenanceWindow:
    id: int
    starts_at: datetime
    ends_at: datetime
    reason: str


@dataclass(frozen=True, slots=True)
class Court:
    id: int
    name: str
    address: str
    size_m2: Decimal
    max_players: int
    hourly_price: Decimal
    surface: Surface
    covered: bool
    created_at: datetime
    updated_at: datetime
    # Janelas de manutenção que ainda não terminaram, em ordem de início.
    maintenance: tuple[MaintenanceWindow, ...] = ()


@dataclass(frozen=True, slots=True)
class CourtPage:
    items: tuple[Court, ...]
    total: int
    page: int
    page_size: int


class BookingStatus(StrEnum):
    CONFIRMED = "confirmed"
    WAITLISTED = "waitlisted"
    CANCELLED = "cancelled"


ACTIVE_BOOKING_STATUSES = (BookingStatus.CONFIRMED, BookingStatus.WAITLISTED)


@dataclass(frozen=True, slots=True)
class Person:
    id: int
    name: str


class Attendance(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    DECLINED = "declined"


@dataclass(frozen=True, slots=True)
class Player:
    id: int
    name: str
    attendance: Attendance


@dataclass(frozen=True, slots=True)
class Booking:
    id: int
    court: Person
    organizer: Person
    players: tuple[Player, ...]
    starts_at: datetime
    ends_at: datetime
    status: BookingStatus
    requested_at: datetime
    cancelled_at: datetime | None
    # Posição na fila entre os pedidos que disputam o mesmo horário; só existe em "waitlisted".
    waitlist_position: int | None = None

    def involves(self, user_id: int) -> bool:
        return self.organizer.id == user_id or any(player.id == user_id for player in self.players)


@dataclass(frozen=True, slots=True)
class Contact:
    """Nome e e-mail de uma conta, para notificações."""

    id: int
    name: str
    email: str


@dataclass(frozen=True, slots=True)
class BookingSlot:
    """Dados mínimos de uma reserva para decidir conflitos e a ordem da fila."""

    id: int
    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True, slots=True)
class BookingPage:
    items: tuple[Booking, ...]
    total: int
    page: int
    page_size: int


class BookingScope(StrEnum):
    """Recortes da lista de reservas como a tela "Minhas reservas" mostra."""

    # Confirmadas que ainda não terminaram.
    UPCOMING = "upcoming"
    # Canceladas e confirmadas que já terminaram (pedidos ainda na fila ficam de fora).
    PAST = "past"


@dataclass(frozen=True, slots=True)
class ScheduleBooking:
    """Reserva confirmada ou na fila, com o necessário para montar a agenda de um dia."""

    id: int
    court_id: int
    organizer_id: int
    starts_at: datetime
    ends_at: datetime
    status: BookingStatus
    player_ids: frozenset[int]


class SlotStatus(StrEnum):
    FREE = "free"
    BOOKED = "booked"
    MINE = "mine"
    MAINTENANCE = "maintenance"


@dataclass(frozen=True, slots=True)
class ScheduleSlot:
    court_id: int
    starts_at: datetime
    ends_at: datetime
    status: SlotStatus
    # Só quando o horário é da própria conta (status "mine").
    booking_id: int | None
    waitlist_size: int
    # Pedido da própria conta na fila desse horário, se houver.
    waitlist_entry_id: int | None


@dataclass(frozen=True, slots=True)
class Schedule:
    date: date
    courts: tuple[Court, ...]
    slots: tuple[ScheduleSlot, ...]
