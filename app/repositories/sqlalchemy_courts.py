from datetime import datetime

from sqlalchemy import delete, exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.data.courts import CreateCourtData, UpdateCourtData
from app.db.models import BookingModel, CourtMaintenanceModel, CourtModel
from app.domain.entities import (
    ACTIVE_BOOKING_STATUSES,
    BlockKind,
    Court,
    CourtPage,
    MaintenanceWindow,
    Surface,
)
from app.domain.exceptions import DuplicateCourtNameError


def to_court(record: CourtModel, maintenance: tuple[MaintenanceWindow, ...] = ()) -> Court:
    return Court(
        id=record.id,
        name=record.name,
        address=record.address,
        size_m2=record.size_m2,
        max_players=record.max_players,
        hourly_price=record.hourly_price,
        surface=Surface(record.surface),
        covered=record.covered,
        created_at=record.created_at,
        updated_at=record.updated_at,
        maintenance=maintenance,
    )


class SqlAlchemyCourtRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _maintenance(self, court_ids: list[int]) -> dict[int, tuple[MaintenanceWindow, ...]]:
        windows: dict[int, list[MaintenanceWindow]] = {court_id: [] for court_id in court_ids}
        if court_ids:
            records = self.session.scalars(
                select(CourtMaintenanceModel)
                .where(
                    CourtMaintenanceModel.court_id.in_(court_ids),
                    CourtMaintenanceModel.ends_at > func.now(),
                )
                .order_by(CourtMaintenanceModel.starts_at, CourtMaintenanceModel.id)
            )
            for item in records:
                windows[item.court_id].append(
                    MaintenanceWindow(
                        item.id, item.starts_at, item.ends_at, item.reason, BlockKind(item.kind)
                    )
                )
        return {court_id: tuple(items) for court_id, items in windows.items()}

    def _to_courts(self, records: list[CourtModel]) -> tuple[Court, ...]:
        maintenance = self._maintenance([record.id for record in records])
        return tuple(to_court(record, maintenance[record.id]) for record in records)

    def _save(self, record: CourtModel) -> Court:
        try:
            self.session.flush()
            self.session.refresh(record)
            court = self._to_courts([record])[0]
            self.session.commit()
            return court
        except IntegrityError as error:
            self.session.rollback()
            constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
            if getattr(error.orig, "sqlstate", None) == "23505" and constraint == "uq_courts_name":
                raise DuplicateCourtNameError from None
            raise

    def create(self, data: CreateCourtData) -> Court:
        record = CourtModel(
            name=data.name,
            address=data.address,
            size_m2=data.size_m2,
            max_players=data.max_players,
            hourly_price=data.hourly_price,
            surface=data.surface.value,
            covered=data.covered,
        )
        self.session.add(record)
        return self._save(record)

    def get(self, court_id: int) -> Court | None:
        record = self.session.get(CourtModel, court_id, populate_existing=True)
        return self._to_courts([record])[0] if record is not None else None

    def all(self) -> tuple[Court, ...]:
        return self._to_courts(
            list(self.session.scalars(select(CourtModel).order_by(CourtModel.id)))
        )

    def list(self, *, page: int, page_size: int, search: str | None) -> CourtPage:
        filters = []
        if search:
            filters.append(CourtModel.name.icontains(search, autoescape=True))
        total = self.session.scalar(select(func.count()).select_from(CourtModel).where(*filters))
        records = self.session.scalars(
            select(CourtModel)
            .where(*filters)
            .order_by(CourtModel.name, CourtModel.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return CourtPage(self._to_courts(list(records)), total or 0, page, page_size)

    def update(self, court_id: int, data: UpdateCourtData) -> Court | None:
        record = self.session.scalar(
            select(CourtModel).where(CourtModel.id == court_id).with_for_update()
        )
        if record is None:
            return None
        for field in ("name", "address", "size_m2", "max_players", "hourly_price", "covered"):
            value = getattr(data, field)
            if value is not None:
                setattr(record, field, value)
        if data.surface is not None:
            record.surface = data.surface.value
        return self._save(record)

    def delete(self, court_id: int) -> bool:
        deleted_id = self.session.scalar(
            delete(CourtModel).where(CourtModel.id == court_id).returning(CourtModel.id)
        )
        self.session.commit()
        return deleted_id is not None

    def has_active_bookings_after(self, court_id: int, moment: datetime) -> bool:
        return bool(
            self.session.scalar(
                select(
                    exists().where(
                        BookingModel.court_id == court_id,
                        BookingModel.status.in_(
                            [status.value for status in ACTIVE_BOOKING_STATUSES]
                        ),
                        BookingModel.ends_at > moment,
                    )
                )
            )
        )
