"""Agenda das quadras.

Regras:
- Uma reserva dura 60 ou 90 minutos e começa em hora cheia ou meia hora (validado no schema).
- Horário livre: o pedido fica "confirmed". Horário ocupado por uma confirmada: o pedido só é
  aceito com join_waitlist=True e fica "waitlisted".
- Quando uma confirmada sai do horário (cancelada, remarcada ou excluída), a fila da quadra é
  percorrida na ordem dos pedidos (requested_at) e cada pedido que agora cabe é confirmado.
- Nenhum pedido (nem promoção da fila) cai em uma janela de manutenção da quadra.
- Toda alteração trava a quadra (lock_court) para que dois pedidos simultâneos não confirmem o
  mesmo horário; a exclusion constraint do banco é a última barreira.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from app.data.bookings import BookingFilters, CreateBookingData, NewBookingData, UpdateBookingData
from app.domain.entities import Attendance, Booking, BookingPage, BookingStatus, Court, User
from app.domain.exceptions import (
    BookingNotEditableError,
    BookingNotFoundError,
    BookingPermissionError,
    CourtNotFoundError,
    CourtUnderMaintenanceError,
    DuplicateBookingError,
    InvalidBookingError,
    OrganizerAttendanceError,
    SlotUnavailableError,
)
from app.repositories.contracts import BookingRepository


def utcnow() -> datetime:
    return datetime.now(UTC)


def promote_waitlist(bookings: BookingRepository, court_id: int, now: datetime) -> list[int]:
    """Confirma, na ordem de pedido, cada pedido da fila cujo horário ficou livre.

    Devolve os ids confirmados, para avisar quem pediu (US15/US16).
    """
    promoted: list[int] = []
    for candidate in bookings.waitlisted(court_id, starting_after=now):
        if bookings.has_maintenance_overlap(court_id, candidate.starts_at, candidate.ends_at):
            continue
        if not bookings.has_confirmed_overlap(
            court_id, candidate.starts_at, candidate.ends_at, exclude_id=None
        ):
            bookings.set_status(candidate.id, BookingStatus.CONFIRMED)
            promoted.append(candidate.id)
    return promoted


class _BookingHandler:
    def __init__(self, bookings: BookingRepository, clock: Callable[[], datetime] = utcnow) -> None:
        self.bookings = bookings
        self.clock = clock
        # O que a última chamada mudou, para as notificações (US16/US17).
        self.promoted: list[int] = []
        self.rescheduled = False
        self.added_players: tuple[int, ...] = ()
        self.removed: Booking | None = None

    def _load(self, booking_id: int, user: User) -> Booking:
        booking = self.bookings.get(booking_id)
        # 404 também para reservas de outras pessoas: não revela que o id existe.
        if booking is None or not (user.is_admin or booking.involves(user.id)):
            raise BookingNotFoundError
        return booking

    def _lock_for_change(
        self, booking_id: int, user: User, *, target_court_id: int | None = None
    ) -> tuple[Court, Booking, Court]:
        """Trava a quadra da reserva (e a de destino, ao trocar de quadra) e valida a alteração.

        As quadras são travadas em ordem de id para duas remarcações cruzadas não se bloquearem.
        Devolve (quadra atual, reserva, quadra de destino).
        """
        court_id = self.bookings.find_court_id(booking_id)
        if court_id is None:
            raise BookingNotFoundError
        locked = {
            item: self.bookings.lock_court(item)
            for item in sorted({court_id, target_court_id or court_id})
        }
        court = locked[court_id]
        if court is None:
            raise BookingNotFoundError
        target = locked[target_court_id or court_id]
        if target is None:
            raise CourtNotFoundError
        # Relida depois do lock: outra requisição pode ter mudado a reserva enquanto esperávamos.
        booking = self._load(booking_id, user)
        if booking.organizer.id != user.id and not user.is_admin:
            raise BookingPermissionError
        if booking.status is BookingStatus.CANCELLED:
            raise BookingNotEditableError("Esta reserva já foi cancelada.")
        if booking.starts_at <= self.clock():
            raise BookingNotEditableError("Reservas que já começaram não podem ser alteradas.")
        if booking.court.id != court_id:
            # Trocou de quadra enquanto esperávamos o lock: o caller tenta de novo do zero.
            raise BookingNotEditableError("A reserva acabou de mudar. Tente de novo.")
        return court, booking, target

    def _require_future(self, starts_at: datetime) -> None:
        if starts_at <= self.clock():
            raise InvalidBookingError("starts_at", "Escolha um horário futuro.")

    def _players(self, court: Court, organizer_id: int, player_ids: tuple[int, ...]):
        others = set(player_ids) - {organizer_id}
        missing = others - self.bookings.existing_user_ids(others)
        if missing:
            ids = ", ".join(str(item) for item in sorted(missing))
            raise InvalidBookingError("player_ids", f"Jogadores não encontrados: {ids}.")
        if len(others) + 1 > court.max_players:
            raise InvalidBookingError(
                "player_ids",
                f"Esta quadra comporta até {court.max_players} jogadores, contando quem reservou.",
            )
        # Quem reservou também joga a partida.
        return (organizer_id, *sorted(others))

    def _status_for(
        self,
        court_id: int,
        organizer_id: int,
        starts_at: datetime,
        ends_at: datetime,
        *,
        join_waitlist: bool,
        exclude_id: int | None = None,
    ) -> BookingStatus:
        if self.bookings.has_maintenance_overlap(court_id, starts_at, ends_at):
            raise CourtUnderMaintenanceError
        if self.bookings.has_user_overlap(
            organizer_id, court_id, starts_at, ends_at, exclude_id=exclude_id
        ):
            raise DuplicateBookingError
        if self.bookings.has_confirmed_overlap(court_id, starts_at, ends_at, exclude_id=exclude_id):
            if not join_waitlist:
                raise SlotUnavailableError
            return BookingStatus.WAITLISTED
        return BookingStatus.CONFIRMED


class CreateBookingHandler(_BookingHandler):
    def handle(self, user: User, data: CreateBookingData) -> Booking:
        ends_at = data.starts_at + timedelta(minutes=data.duration_minutes)
        self._require_future(data.starts_at)
        with self.bookings.transaction():
            court = self.bookings.lock_court(data.court_id)
            if court is None:
                raise CourtNotFoundError
            players = self._players(court, user.id, data.player_ids)
            status = self._status_for(
                court.id, user.id, data.starts_at, ends_at, join_waitlist=data.join_waitlist
            )
            booking_id = self.bookings.add(
                NewBookingData(court.id, user.id, data.starts_at, ends_at, status, players)
            )
        return self._load(booking_id, user)


class GetBookingHandler(_BookingHandler):
    def handle(self, user: User, booking_id: int) -> Booking:
        return self._load(booking_id, user)


class ListBookingsHandler(_BookingHandler):
    def handle(
        self, user: User, filters: BookingFilters, *, page: int = 1, page_size: int = 20
    ) -> BookingPage:
        visible = BookingFilters(
            court_id=filters.court_id,
            status=filters.status,
            starts_from=filters.starts_from,
            starts_to=filters.starts_to,
            scope=filters.scope,
            # Admin vê todas, a menos que peça só as próprias (filters.visible_to).
            visible_to=user.id if not user.is_admin or filters.visible_to is not None else None,
            now=self.clock(),
        )
        return self.bookings.list(visible, page=page, page_size=page_size)


class UpdateBookingHandler(_BookingHandler):
    """Troca os jogadores e/ou remarca (horário, duração e quadra).

    Remarcar volta a presença dos convidados para "pending": eles confirmam o novo horário.
    """

    def handle(self, user: User, booking_id: int, data: UpdateBookingData) -> Booking:
        with self.bookings.transaction():
            court, booking, target = self._lock_for_change(
                booking_id, user, target_court_id=data.court_id
            )
            organizer_id = booking.organizer.id
            if data.player_ids is not None or target.id != court.id:
                # A quadra de destino pode comportar menos jogadores.
                player_ids = (
                    data.player_ids
                    if data.player_ids is not None
                    else tuple(player.id for player in booking.players)
                )
                players = self._players(target, organizer_id, player_ids)
                if data.player_ids is not None:
                    before = {player.id for player in booking.players}
                    self.bookings.replace_players(booking_id, players, organizer_id=organizer_id)
                    self.added_players = tuple(item for item in players if item not in before)

            starts_at = data.starts_at or booking.starts_at
            duration = data.duration_minutes or int(
                (booking.ends_at - booking.starts_at).total_seconds() // 60
            )
            ends_at = starts_at + timedelta(minutes=duration)
            current = (court.id, booking.starts_at, booking.ends_at)
            if (target.id, starts_at, ends_at) != current:
                self._require_future(starts_at)
                status = self._status_for(
                    target.id,
                    organizer_id,
                    starts_at,
                    ends_at,
                    join_waitlist=data.join_waitlist,
                    exclude_id=booking_id,
                )
                self.bookings.reschedule(
                    booking_id,
                    court_id=target.id,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    status=status,
                )
                self.bookings.reset_attendance(booking_id, organizer_id=organizer_id)
                self.rescheduled = True
                # O horário antigo pode ter liberado espaço para a fila da quadra de origem.
                self.promoted = promote_waitlist(self.bookings, court.id, self.clock())
        return self._load(booking_id, user)


class CancelBookingHandler(_BookingHandler):
    """Cancela a reserva (ou sai da fila). O registro fica no histórico."""

    def handle(self, user: User, booking_id: int) -> Booking:
        now = self.clock()
        with self.bookings.transaction():
            court, booking, _ = self._lock_for_change(booking_id, user)
            self.removed = booking  # Estado antes do cancelamento, para o aviso (US17).
            self.bookings.set_status(booking_id, BookingStatus.CANCELLED, cancelled_at=now)
            if booking.status is BookingStatus.CONFIRMED:
                self.promoted = promote_waitlist(self.bookings, court.id, now)
        return self._load(booking_id, user)


class DeleteBookingHandler(_BookingHandler):
    """Exclusão definitiva, restrita a administradores pela rota."""

    def handle(self, user: User, booking_id: int) -> None:
        now = self.clock()
        with self.bookings.transaction():
            court_id = self.bookings.find_court_id(booking_id)
            if court_id is None or self.bookings.lock_court(court_id) is None:
                raise BookingNotFoundError
            booking = self._load(booking_id, user)
            self.bookings.delete(booking_id)
            if booking.starts_at > now and booking.status is not BookingStatus.CANCELLED:
                self.removed = booking
            if booking.status is BookingStatus.CONFIRMED and booking.starts_at > now:
                self.promoted = promote_waitlist(self.bookings, court_id, now)


class RespondAttendanceHandler(_BookingHandler):
    """Convidado confirma ou recusa presença na partida."""

    def handle(self, user: User, booking_id: int, attendance: Attendance) -> Booking:
        with self.bookings.transaction():
            booking = self.bookings.get(booking_id)
            if booking is None or not any(player.id == user.id for player in booking.players):
                # Admin que não joga a partida também recebe 404: só convidados respondem.
                raise BookingNotFoundError
            if booking.organizer.id == user.id:
                raise OrganizerAttendanceError
            if booking.status is BookingStatus.CANCELLED:
                raise BookingNotEditableError("Esta reserva já foi cancelada.")
            if booking.starts_at <= self.clock():
                raise BookingNotEditableError("Reservas que já começaram não podem ser alteradas.")
            self.bookings.set_attendance(booking_id, user.id, attendance)
        return self._load(booking_id, user)
