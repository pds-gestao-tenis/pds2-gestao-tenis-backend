from collections.abc import Sequence
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Protocol

from app.data.bookings import BookingFilters, NewBookingData
from app.data.courts import CreateCourtData, MaintenanceData, UpdateCourtData
from app.data.members import CreateMemberData, UpdateMemberData
from app.domain.entities import (
    Attendance,
    AuthenticatedSession,
    Booking,
    BookingPage,
    BookingSlot,
    BookingStatus,
    Contact,
    Court,
    CourtPage,
    Member,
    MemberPage,
    MemberStatus,
    Person,
    ScheduleBooking,
    User,
    UserCredentials,
)


class UserRepository(Protocol):
    def create(self, *, name: str, email: str, password_hash: str) -> User: ...

    def find_credentials_by_email(self, email: str) -> UserCredentials | None: ...

    def promote_administrator(self, email: str) -> User | None: ...

    def search(self, term: str, *, exclude_id: int, limit: int) -> Sequence[Person]: ...


class SessionRepository(Protocol):
    def create(self, *, user_id: int, token_hash: str, expires_at: datetime) -> None: ...

    def find_active(self, token_hash: str, now: datetime) -> AuthenticatedSession | None: ...

    def revoke(self, token_hash: str, now: datetime) -> bool: ...


class MemberRepository(Protocol):
    def create(self, data: CreateMemberData) -> Member: ...

    def get(self, member_id: int) -> Member | None: ...

    def list(
        self,
        *,
        page: int,
        page_size: int,
        status: MemberStatus | None,
        search: str | None,
    ) -> MemberPage: ...

    def update(self, member_id: int, data: UpdateMemberData) -> Member | None: ...

    def delete(self, member_id: int) -> bool: ...


class CourtRepository(Protocol):
    def create(self, data: CreateCourtData) -> Court: ...

    def get(self, court_id: int) -> Court | None: ...

    def all(self) -> tuple[Court, ...]: ...

    def list(self, *, page: int, page_size: int, search: str | None) -> CourtPage: ...

    def update(self, court_id: int, data: UpdateCourtData) -> Court | None: ...

    def delete(self, court_id: int) -> bool: ...

    def has_active_bookings_after(self, court_id: int, moment: datetime) -> bool: ...


class BookingRepository(Protocol):
    """Operações da agenda. As alterações só valem dentro de transaction()."""

    def transaction(self) -> AbstractContextManager[None]: ...

    def lock_court(self, court_id: int) -> Court | None: ...

    def find_court_id(self, booking_id: int) -> int | None: ...

    def existing_user_ids(self, user_ids: set[int]) -> set[int]: ...

    def has_confirmed_overlap(
        self, court_id: int, starts_at: datetime, ends_at: datetime, *, exclude_id: int | None
    ) -> bool: ...

    def has_user_overlap(
        self,
        user_id: int,
        court_id: int,
        starts_at: datetime,
        ends_at: datetime,
        *,
        exclude_id: int | None,
    ) -> bool: ...

    def has_maintenance_overlap(
        self, court_id: int, starts_at: datetime, ends_at: datetime
    ) -> bool: ...

    def active_overlapping(
        self, court_id: int, starts_at: datetime, ends_at: datetime, *, starting_after: datetime
    ) -> Sequence[BookingSlot]: ...

    def add_maintenance(self, court_id: int, data: MaintenanceData) -> int: ...

    def delete_maintenance(self, court_id: int, maintenance_id: int) -> bool: ...

    def add(self, data: NewBookingData) -> int: ...

    def get(self, booking_id: int) -> Booking | None: ...

    def list(self, filters: BookingFilters, *, page: int, page_size: int) -> BookingPage: ...

    def reschedule(
        self,
        booking_id: int,
        *,
        court_id: int,
        starts_at: datetime,
        ends_at: datetime,
        status: BookingStatus,
    ) -> None: ...

    def replace_players(
        self, booking_id: int, user_ids: tuple[int, ...], *, organizer_id: int
    ) -> None: ...

    def reset_attendance(self, booking_id: int, *, organizer_id: int) -> None: ...

    def set_attendance(self, booking_id: int, user_id: int, attendance: Attendance) -> None: ...

    def day_bookings(self, starts_at: datetime, ends_at: datetime) -> Sequence[ScheduleBooking]: ...

    def set_status(
        self, booking_id: int, status: BookingStatus, *, cancelled_at: datetime | None = None
    ) -> None: ...

    def waitlisted(self, court_id: int, *, starting_after: datetime) -> Sequence[BookingSlot]: ...

    def delete(self, booking_id: int) -> None: ...

    def contacts(self, user_ids: set[int]) -> dict[int, Contact]: ...

    def due_for_reminder(self, starts_from: datetime, starts_to: datetime) -> Sequence[int]: ...

    def mark_reminded(self, booking_ids: Sequence[int], sent_at: datetime) -> None: ...
