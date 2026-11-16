from collections.abc import Iterator
from datetime import timedelta
from functools import cache
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from app.core.passwords import PasswordVerifier
from app.core.tokens import TokenService
from app.domain.entities import AuthenticatedSession, User
from app.domain.exceptions import AuthenticationError
from app.handlers.administrator import RequireAdministratorHandler
from app.handlers.authenticate_session import AuthenticateSessionHandler
from app.handlers.bookings import (
    CancelBookingHandler,
    CreateBookingHandler,
    DeleteBookingHandler,
    GetBookingHandler,
    ListBookingsHandler,
    RespondAttendanceHandler,
    UpdateBookingHandler,
)
from app.handlers.courts import (
    AddMaintenanceHandler,
    CreateCourtHandler,
    DeleteCourtHandler,
    GetCourtHandler,
    ListCourtsHandler,
    RemoveMaintenanceHandler,
    UpdateCourtHandler,
)
from app.handlers.login_user import LoginUserHandler
from app.handlers.logout_user import LogoutUserHandler
from app.handlers.members import (
    CreateMemberHandler,
    DeleteMemberHandler,
    GetMemberHandler,
    ListMembersHandler,
    UpdateMemberHandler,
)
from app.handlers.register_user import RegisterUserHandler
from app.handlers.schedule import GetScheduleHandler, SearchPlayersHandler
from app.repositories.sqlalchemy_bookings import SqlAlchemyBookingRepository
from app.repositories.sqlalchemy_courts import SqlAlchemyCourtRepository
from app.repositories.sqlalchemy_members import SqlAlchemyMemberRepository
from app.repositories.sqlalchemy_sessions import SqlAlchemySessionRepository
from app.repositories.sqlalchemy_users import SqlAlchemyUserRepository


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


@cache
def get_password_hasher() -> PasswordHash:
    return PasswordHash.recommended()


def get_register_handler(
    session: Annotated[Session, Depends(get_session)],
) -> RegisterUserHandler:
    return RegisterUserHandler(SqlAlchemyUserRepository(session), get_password_hasher())


bearer_auth = HTTPBearer(
    auto_error=False,
    scheme_name="BearerAuth",
    description="Cole o access_token retornado pelo login. A sessão expira e pode ser revogada.",
)


@cache
def get_password_verifier() -> PasswordVerifier:
    return PasswordVerifier(get_password_hasher())


def get_login_handler(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> LoginUserHandler:
    return LoginUserHandler(
        SqlAlchemyUserRepository(session),
        SqlAlchemySessionRepository(session),
        get_password_verifier(),
        TokenService(),
        ttl=timedelta(minutes=request.app.state.settings.access_token_ttl_minutes),
    )


def get_current_session(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_auth)],
    session: Annotated[Session, Depends(get_session)],
) -> AuthenticatedSession:
    if credentials is None:
        raise AuthenticationError
    return AuthenticateSessionHandler(SqlAlchemySessionRepository(session), TokenService()).handle(
        credentials.credentials
    )


def get_logout_handler(
    session: Annotated[Session, Depends(get_session)],
) -> LogoutUserHandler:
    return LogoutUserHandler(SqlAlchemySessionRepository(session))


def require_administrator(
    context: Annotated[AuthenticatedSession, Depends(get_current_session)],
) -> User:
    return RequireAdministratorHandler().handle(context)


def get_member_repository(
    session: Annotated[Session, Depends(get_session)],
) -> SqlAlchemyMemberRepository:
    return SqlAlchemyMemberRepository(session)


def get_create_member_handler(
    members: Annotated[SqlAlchemyMemberRepository, Depends(get_member_repository)],
) -> CreateMemberHandler:
    return CreateMemberHandler(members)


def get_list_members_handler(
    members: Annotated[SqlAlchemyMemberRepository, Depends(get_member_repository)],
) -> ListMembersHandler:
    return ListMembersHandler(members)


def get_member_handler(
    members: Annotated[SqlAlchemyMemberRepository, Depends(get_member_repository)],
) -> GetMemberHandler:
    return GetMemberHandler(members)


def get_update_member_handler(
    members: Annotated[SqlAlchemyMemberRepository, Depends(get_member_repository)],
) -> UpdateMemberHandler:
    return UpdateMemberHandler(members)


def get_delete_member_handler(
    members: Annotated[SqlAlchemyMemberRepository, Depends(get_member_repository)],
) -> DeleteMemberHandler:
    return DeleteMemberHandler(members)


def get_current_user(
    context: Annotated[AuthenticatedSession, Depends(get_current_session)],
) -> User:
    return context.user


def get_court_repository(
    session: Annotated[Session, Depends(get_session)],
) -> SqlAlchemyCourtRepository:
    return SqlAlchemyCourtRepository(session)


CourtRepositoryDependency = Annotated[SqlAlchemyCourtRepository, Depends(get_court_repository)]


def get_create_court_handler(courts: CourtRepositoryDependency) -> CreateCourtHandler:
    return CreateCourtHandler(courts)


def get_list_courts_handler(courts: CourtRepositoryDependency) -> ListCourtsHandler:
    return ListCourtsHandler(courts)


def get_court_handler(courts: CourtRepositoryDependency) -> GetCourtHandler:
    return GetCourtHandler(courts)


def get_update_court_handler(courts: CourtRepositoryDependency) -> UpdateCourtHandler:
    return UpdateCourtHandler(courts)


def get_delete_court_handler(courts: CourtRepositoryDependency) -> DeleteCourtHandler:
    return DeleteCourtHandler(courts)


def get_booking_repository(
    session: Annotated[Session, Depends(get_session)],
) -> SqlAlchemyBookingRepository:
    return SqlAlchemyBookingRepository(session)


BookingRepositoryDependency = Annotated[
    SqlAlchemyBookingRepository, Depends(get_booking_repository)
]


def get_create_booking_handler(bookings: BookingRepositoryDependency) -> CreateBookingHandler:
    return CreateBookingHandler(bookings)


def get_list_bookings_handler(bookings: BookingRepositoryDependency) -> ListBookingsHandler:
    return ListBookingsHandler(bookings)


def get_booking_handler(bookings: BookingRepositoryDependency) -> GetBookingHandler:
    return GetBookingHandler(bookings)


def get_update_booking_handler(bookings: BookingRepositoryDependency) -> UpdateBookingHandler:
    return UpdateBookingHandler(bookings)


def get_cancel_booking_handler(bookings: BookingRepositoryDependency) -> CancelBookingHandler:
    return CancelBookingHandler(bookings)


def get_delete_booking_handler(bookings: BookingRepositoryDependency) -> DeleteBookingHandler:
    return DeleteBookingHandler(bookings)


def get_add_maintenance_handler(
    bookings: BookingRepositoryDependency, courts: CourtRepositoryDependency
) -> AddMaintenanceHandler:
    return AddMaintenanceHandler(bookings, courts)


def get_remove_maintenance_handler(
    bookings: BookingRepositoryDependency, courts: CourtRepositoryDependency
) -> RemoveMaintenanceHandler:
    return RemoveMaintenanceHandler(bookings, courts)


def get_attendance_handler(bookings: BookingRepositoryDependency) -> RespondAttendanceHandler:
    return RespondAttendanceHandler(bookings)


def get_schedule_handler(
    request: Request,
    courts: CourtRepositoryDependency,
    bookings: BookingRepositoryDependency,
) -> GetScheduleHandler:
    return GetScheduleHandler(courts, bookings, ZoneInfo(request.app.state.settings.club_timezone))


def get_search_players_handler(
    session: Annotated[Session, Depends(get_session)],
) -> SearchPlayersHandler:
    return SearchPlayersHandler(SqlAlchemyUserRepository(session))
