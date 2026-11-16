from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import and_, delete, exists, func, insert, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.data.bookings import BookingFilters, NewBookingData
from app.data.courts import MaintenanceData
from app.db.models import (
    BookingModel,
    BookingPlayerModel,
    CourtMaintenanceModel,
    CourtModel,
    UserModel,
)
from app.domain.entities import (
    ACTIVE_BOOKING_STATUSES,
    Attendance,
    Booking,
    BookingPage,
    BookingScope,
    BookingSlot,
    BookingStatus,
    Court,
    Person,
    Player,
    ScheduleBooking,
)
from app.domain.exceptions import SlotUnavailableError
from app.repositories.sqlalchemy_courts import to_court

ACTIVE = [status.value for status in ACTIVE_BOOKING_STATUSES]


def overlaps(starts_at: datetime, ends_at: datetime):
    # Intervalos semiabertos: uma reserva que termina às 19:00 não conflita com a das 19:00.
    return and_(BookingModel.starts_at < ends_at, BookingModel.ends_at > starts_at)


class SqlAlchemyBookingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    @contextmanager
    def transaction(self) -> Iterator[None]:
        try:
            yield
            self.session.commit()
        except IntegrityError as error:
            self.session.rollback()
            # 23P01: a exclusion constraint barrou duas confirmadas no mesmo horário (corrida).
            if getattr(error.orig, "sqlstate", None) == "23P01":
                raise SlotUnavailableError from None
            raise
        except BaseException:
            self.session.rollback()
            raise

    def lock_court(self, court_id: int) -> Court | None:
        # Serializa as alterações da agenda de uma quadra: quem chega depois espera o commit.
        record = self.session.scalar(
            select(CourtModel).where(CourtModel.id == court_id).with_for_update()
        )
        return to_court(record) if record is not None else None

    def find_court_id(self, booking_id: int) -> int | None:
        return self.session.scalar(
            select(BookingModel.court_id).where(BookingModel.id == booking_id)
        )

    def existing_user_ids(self, user_ids: set[int]) -> set[int]:
        if not user_ids:
            return set()
        return set(self.session.scalars(select(UserModel.id).where(UserModel.id.in_(user_ids))))

    def has_confirmed_overlap(
        self, court_id: int, starts_at: datetime, ends_at: datetime, *, exclude_id: int | None
    ) -> bool:
        conditions = [
            BookingModel.court_id == court_id,
            BookingModel.status == BookingStatus.CONFIRMED.value,
            overlaps(starts_at, ends_at),
        ]
        if exclude_id is not None:
            conditions.append(BookingModel.id != exclude_id)
        return bool(self.session.scalar(select(exists().where(*conditions))))

    def has_user_overlap(
        self,
        user_id: int,
        court_id: int,
        starts_at: datetime,
        ends_at: datetime,
        *,
        exclude_id: int | None,
    ) -> bool:
        conditions = [
            BookingModel.user_id == user_id,
            BookingModel.court_id == court_id,
            BookingModel.status.in_(ACTIVE),
            overlaps(starts_at, ends_at),
        ]
        if exclude_id is not None:
            conditions.append(BookingModel.id != exclude_id)
        return bool(self.session.scalar(select(exists().where(*conditions))))

    def has_maintenance_overlap(
        self, court_id: int, starts_at: datetime, ends_at: datetime
    ) -> bool:
        return bool(
            self.session.scalar(
                select(
                    exists().where(
                        CourtMaintenanceModel.court_id == court_id,
                        CourtMaintenanceModel.starts_at < ends_at,
                        CourtMaintenanceModel.ends_at > starts_at,
                    )
                )
            )
        )

    def active_overlapping(
        self, court_id: int, starts_at: datetime, ends_at: datetime, *, starting_after: datetime
    ) -> Sequence[BookingSlot]:
        rows = self.session.execute(
            select(BookingModel.id, BookingModel.starts_at, BookingModel.ends_at)
            .where(
                BookingModel.court_id == court_id,
                BookingModel.status.in_(ACTIVE),
                BookingModel.starts_at > starting_after,
                overlaps(starts_at, ends_at),
            )
            .order_by(BookingModel.starts_at, BookingModel.id)
        )
        return [BookingSlot(row.id, row.starts_at, row.ends_at) for row in rows]

    def add_maintenance(self, court_id: int, data: MaintenanceData) -> int:
        return self.session.scalar(
            insert(CourtMaintenanceModel)
            .values(
                court_id=court_id,
                starts_at=data.starts_at,
                ends_at=data.ends_at,
                reason=data.reason,
            )
            .returning(CourtMaintenanceModel.id)
        )

    def delete_maintenance(self, court_id: int, maintenance_id: int) -> bool:
        deleted = self.session.scalar(
            delete(CourtMaintenanceModel)
            .where(
                CourtMaintenanceModel.id == maintenance_id,
                CourtMaintenanceModel.court_id == court_id,
            )
            .returning(CourtMaintenanceModel.id)
        )
        return deleted is not None

    def add(self, data: NewBookingData) -> int:
        booking_id = self.session.scalar(
            insert(BookingModel)
            .values(
                court_id=data.court_id,
                user_id=data.user_id,
                starts_at=data.starts_at,
                ends_at=data.ends_at,
                status=data.status.value,
                # clock_timestamp(), e não now(): now() é fixo na transação e empataria a fila.
                requested_at=func.clock_timestamp(),
            )
            .returning(BookingModel.id)
        )
        self.replace_players(booking_id, data.player_ids, organizer_id=data.user_id)
        return booking_id

    def reschedule(
        self,
        booking_id: int,
        *,
        court_id: int,
        starts_at: datetime,
        ends_at: datetime,
        status: BookingStatus,
    ) -> None:
        self.session.execute(
            update(BookingModel)
            .where(BookingModel.id == booking_id)
            .values(
                court_id=court_id,
                starts_at=starts_at,
                ends_at=ends_at,
                status=status.value,
                # Novo horário é um novo pedido: vai para o fim da fila desse horário.
                requested_at=func.clock_timestamp(),
                updated_at=func.now(),
            )
        )

    def replace_players(
        self, booking_id: int, user_ids: tuple[int, ...], *, organizer_id: int
    ) -> None:
        # Quem continua na partida mantém a resposta; quem entra começa pendente.
        current = dict(
            self.session.execute(
                select(BookingPlayerModel.user_id, BookingPlayerModel.attendance).where(
                    BookingPlayerModel.booking_id == booking_id
                )
            ).all()
        )
        self.session.execute(
            delete(BookingPlayerModel).where(BookingPlayerModel.booking_id == booking_id)
        )
        if user_ids:
            self.session.execute(
                insert(BookingPlayerModel),
                [
                    {
                        "booking_id": booking_id,
                        "user_id": user_id,
                        "attendance": (
                            Attendance.CONFIRMED.value
                            if user_id == organizer_id
                            else current.get(user_id, Attendance.PENDING.value)
                        ),
                    }
                    for user_id in user_ids
                ],
            )

    def reset_attendance(self, booking_id: int, *, organizer_id: int) -> None:
        self.session.execute(
            update(BookingPlayerModel)
            .where(
                BookingPlayerModel.booking_id == booking_id,
                BookingPlayerModel.user_id != organizer_id,
            )
            .values(attendance=Attendance.PENDING.value)
        )

    def set_attendance(self, booking_id: int, user_id: int, attendance: Attendance) -> None:
        self.session.execute(
            update(BookingPlayerModel)
            .where(
                BookingPlayerModel.booking_id == booking_id,
                BookingPlayerModel.user_id == user_id,
            )
            .values(attendance=attendance.value)
        )

    def day_bookings(self, starts_at: datetime, ends_at: datetime) -> Sequence[ScheduleBooking]:
        records = list(
            self.session.scalars(
                select(BookingModel)
                .where(BookingModel.status.in_(ACTIVE), overlaps(starts_at, ends_at))
                .order_by(BookingModel.requested_at, BookingModel.id)
            )
        )
        players: dict[int, set[int]] = {record.id: set() for record in records}
        if records:
            for booking_id, user_id in self.session.execute(
                select(BookingPlayerModel.booking_id, BookingPlayerModel.user_id).where(
                    BookingPlayerModel.booking_id.in_(players)
                )
            ):
                players[booking_id].add(user_id)
        return [
            ScheduleBooking(
                record.id,
                record.court_id,
                record.user_id,
                record.starts_at,
                record.ends_at,
                BookingStatus(record.status),
                frozenset(players[record.id]),
            )
            for record in records
        ]

    def set_status(
        self, booking_id: int, status: BookingStatus, *, cancelled_at: datetime | None = None
    ) -> None:
        self.session.execute(
            update(BookingModel)
            .where(BookingModel.id == booking_id)
            .values(status=status.value, cancelled_at=cancelled_at, updated_at=func.now())
        )

    def waitlisted(self, court_id: int, *, starting_after: datetime) -> Sequence[BookingSlot]:
        rows = self.session.execute(
            select(BookingModel.id, BookingModel.starts_at, BookingModel.ends_at)
            .where(
                BookingModel.court_id == court_id,
                BookingModel.status == BookingStatus.WAITLISTED.value,
                BookingModel.starts_at > starting_after,
            )
            .order_by(BookingModel.requested_at, BookingModel.id)
        )
        return [BookingSlot(row.id, row.starts_at, row.ends_at) for row in rows]

    def delete(self, booking_id: int) -> None:
        self.session.execute(delete(BookingModel).where(BookingModel.id == booking_id))

    # ---------- Leitura ----------

    def _select(self):
        organizer = aliased(UserModel)
        return (
            select(
                BookingModel, CourtModel.name.label("court_name"), organizer.name.label("organizer")
            )
            .join(CourtModel, CourtModel.id == BookingModel.court_id)
            .join(organizer, organizer.id == BookingModel.user_id)
        )

    def _players(self, booking_ids: list[int]) -> dict[int, list[Player]]:
        players: dict[int, list[Player]] = {booking_id: [] for booking_id in booking_ids}
        if booking_ids:
            rows = self.session.execute(
                select(
                    BookingPlayerModel.booking_id,
                    BookingPlayerModel.attendance,
                    UserModel.id,
                    UserModel.name,
                )
                .join(UserModel, UserModel.id == BookingPlayerModel.user_id)
                .where(BookingPlayerModel.booking_id.in_(booking_ids))
                .order_by(UserModel.name, UserModel.id)
            )
            for row in rows:
                players[row.booking_id].append(Player(row.id, row.name, Attendance(row.attendance)))
        return players

    def _position(self, record: BookingModel) -> int:
        # Pedidos anteriores na fila que disputam ao menos parte do mesmo horário.
        ahead = self.session.scalar(
            select(func.count())
            .select_from(BookingModel)
            .where(
                BookingModel.court_id == record.court_id,
                BookingModel.status == BookingStatus.WAITLISTED.value,
                overlaps(record.starts_at, record.ends_at),
                or_(
                    BookingModel.requested_at < record.requested_at,
                    and_(
                        BookingModel.requested_at == record.requested_at,
                        BookingModel.id < record.id,
                    ),
                ),
            )
        )
        return (ahead or 0) + 1

    def _to_bookings(self, rows) -> tuple[Booking, ...]:
        rows = list(rows)
        players = self._players([row.BookingModel.id for row in rows])
        result = []
        for row in rows:
            record: BookingModel = row.BookingModel
            status = BookingStatus(record.status)
            result.append(
                Booking(
                    id=record.id,
                    court=Person(record.court_id, row.court_name),
                    organizer=Person(record.user_id, row.organizer),
                    players=tuple(players[record.id]),
                    starts_at=record.starts_at,
                    ends_at=record.ends_at,
                    status=status,
                    requested_at=record.requested_at,
                    cancelled_at=record.cancelled_at,
                    waitlist_position=(
                        self._position(record) if status is BookingStatus.WAITLISTED else None
                    ),
                )
            )
        return tuple(result)

    def get(self, booking_id: int) -> Booking | None:
        bookings = self._to_bookings(
            self.session.execute(self._select().where(BookingModel.id == booking_id))
        )
        return bookings[0] if bookings else None

    def list(self, filters: BookingFilters, *, page: int, page_size: int) -> BookingPage:
        conditions = []
        if filters.court_id is not None:
            conditions.append(BookingModel.court_id == filters.court_id)
        if filters.status is not None:
            conditions.append(BookingModel.status == filters.status.value)
        if filters.starts_from is not None:
            conditions.append(BookingModel.starts_at >= filters.starts_from)
        if filters.starts_to is not None:
            conditions.append(BookingModel.starts_at < filters.starts_to)
        order = [BookingModel.starts_at, BookingModel.id]
        if filters.scope is not None:
            now = filters.now or func.now()
            confirmed = BookingModel.status == BookingStatus.CONFIRMED.value
            if filters.scope is BookingScope.UPCOMING:
                conditions.append(and_(confirmed, BookingModel.ends_at > now))
            else:
                conditions.append(
                    or_(
                        BookingModel.status == BookingStatus.CANCELLED.value,
                        and_(confirmed, BookingModel.ends_at <= now),
                    )
                )
                # Histórico: o mais recente primeiro.
                order = [BookingModel.starts_at.desc(), BookingModel.id.desc()]
        if filters.visible_to is not None:
            conditions.append(
                or_(
                    BookingModel.user_id == filters.visible_to,
                    exists().where(
                        BookingPlayerModel.booking_id == BookingModel.id,
                        BookingPlayerModel.user_id == filters.visible_to,
                    ),
                )
            )
        total = self.session.scalar(
            select(func.count()).select_from(BookingModel).where(*conditions)
        )
        rows = self.session.execute(
            self._select()
            .where(*conditions)
            .order_by(*order)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return BookingPage(self._to_bookings(rows), total or 0, page, page_size)
