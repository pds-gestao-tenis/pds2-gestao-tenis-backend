from collections.abc import Callable
from datetime import UTC, datetime

from app.data.courts import CreateCourtData, MaintenanceData, UpdateCourtData
from app.domain.entities import BookingStatus, Court, CourtPage
from app.domain.exceptions import (
    CourtInUseError,
    CourtNotFoundError,
    InvalidBookingError,
    MaintenanceConflictError,
    MaintenanceNotFoundError,
)
from app.handlers.bookings import promote_waitlist
from app.repositories.contracts import BookingRepository, CourtRepository


def utcnow() -> datetime:
    return datetime.now(UTC)


class CreateCourtHandler:
    def __init__(self, courts: CourtRepository) -> None:
        self.courts = courts

    def handle(self, data: CreateCourtData) -> Court:
        return self.courts.create(data)


class GetCourtHandler:
    def __init__(self, courts: CourtRepository) -> None:
        self.courts = courts

    def handle(self, court_id: int) -> Court:
        court = self.courts.get(court_id)
        if court is None:
            raise CourtNotFoundError
        return court


class ListCourtsHandler:
    def __init__(self, courts: CourtRepository) -> None:
        self.courts = courts

    def handle(self, *, page: int = 1, page_size: int = 20, search: str | None = None) -> CourtPage:
        return self.courts.list(page=page, page_size=page_size, search=search)


class UpdateCourtHandler:
    def __init__(self, courts: CourtRepository) -> None:
        self.courts = courts

    def handle(self, court_id: int, data: UpdateCourtData) -> Court:
        court = self.courts.update(court_id, data)
        if court is None:
            raise CourtNotFoundError
        return court


class DeleteCourtHandler:
    """Exclui a quadra e seu histórico; recusa se ainda houver reservas ou fila por vir."""

    def __init__(self, courts: CourtRepository, clock: Callable[[], datetime] = utcnow) -> None:
        self.courts = courts
        self.clock = clock

    def handle(self, court_id: int) -> None:
        if self.courts.get(court_id) is None:
            raise CourtNotFoundError
        if self.courts.has_active_bookings_after(court_id, self.clock()):
            raise CourtInUseError
        if not self.courts.delete(court_id):
            raise CourtNotFoundError


class AddMaintenanceHandler:
    """Bloqueia um período da quadra.

    Reservas confirmadas e pedidos na fila que ainda não começaram e caem no período impedem a
    manutenção (409), a menos que cancel_bookings=True: nesse caso são cancelados.
    """

    def __init__(
        self,
        bookings: BookingRepository,
        courts: CourtRepository,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.bookings = bookings
        self.courts = courts
        self.clock = clock
        # Reservas canceladas pela manutenção e pedidos da fila confirmados (notificações).
        self.cancelled: list[int] = []
        self.promoted: list[int] = []

    def handle(self, court_id: int, data: MaintenanceData) -> Court:
        now = self.clock()
        if data.ends_at <= now:
            raise InvalidBookingError("ends_at", "A manutenção precisa terminar no futuro.")
        with self.bookings.transaction():
            if self.bookings.lock_court(court_id) is None:
                raise CourtNotFoundError
            affected = self.bookings.active_overlapping(
                court_id, data.starts_at, data.ends_at, starting_after=now
            )
            if affected and not data.cancel_bookings:
                raise MaintenanceConflictError(len(affected))
            for booking in affected:
                self.bookings.set_status(booking.id, BookingStatus.CANCELLED, cancelled_at=now)
            self.cancelled = [booking.id for booking in affected]
            self.bookings.add_maintenance(court_id, data)
            # Reservas canceladas que passavam do período podem liberar horário para a fila.
            self.promoted = promote_waitlist(self.bookings, court_id, now)
        return self.courts.get(court_id)


class RemoveMaintenanceHandler:
    def __init__(
        self,
        bookings: BookingRepository,
        courts: CourtRepository,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.bookings = bookings
        self.courts = courts
        self.clock = clock

    def handle(self, court_id: int, maintenance_id: int) -> Court:
        with self.bookings.transaction():
            if self.bookings.lock_court(court_id) is None:
                raise CourtNotFoundError
            if not self.bookings.delete_maintenance(court_id, maintenance_id):
                raise MaintenanceNotFoundError
        return self.courts.get(court_id)
