from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import BookingModel, CourtMaintenanceModel, CourtModel
from app.domain.entities import BookingStatus, Person


@dataclass(frozen=True, slots=True)
class Interval:
    court_id: int
    starts_at: datetime
    ends_at: datetime


class SqlAlchemyReportRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def courts(self) -> Sequence[Person]:
        rows = self.session.execute(
            select(CourtModel.id, CourtModel.name).order_by(CourtModel.name, CourtModel.id)
        )
        return [Person(row.id, row.name) for row in rows]

    def confirmed_bookings(self, starts: datetime, ends: datetime) -> Sequence[Interval]:
        rows = self.session.execute(
            select(BookingModel.court_id, BookingModel.starts_at, BookingModel.ends_at).where(
                BookingModel.status == BookingStatus.CONFIRMED.value,
                BookingModel.starts_at < ends,
                BookingModel.ends_at > starts,
            )
        )
        return [Interval(row.court_id, row.starts_at, row.ends_at) for row in rows]

    def cancelled_count(self, starts: datetime, ends: datetime) -> int:
        return (
            self.session.scalar(
                select(func.count()).where(
                    BookingModel.status == BookingStatus.CANCELLED.value,
                    BookingModel.starts_at >= starts,
                    BookingModel.starts_at < ends,
                )
            )
            or 0
        )

    def blocks(self, starts: datetime, ends: datetime) -> Sequence[Interval]:
        rows = self.session.execute(
            select(
                CourtMaintenanceModel.court_id,
                CourtMaintenanceModel.starts_at,
                CourtMaintenanceModel.ends_at,
            ).where(CourtMaintenanceModel.starts_at < ends, CourtMaintenanceModel.ends_at > starts)
        )
        return [Interval(row.court_id, row.starts_at, row.ends_at) for row in rows]
