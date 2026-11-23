from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Path, Query, Response, status
from pydantic import AwareDatetime

from app.core.mailer import Mailer, send_all
from app.data.bookings import BookingFilters, CreateBookingData, UpdateBookingData
from app.dependencies import (
    get_attendance_handler,
    get_booking_handler,
    get_booking_notifier,
    get_cancel_booking_handler,
    get_create_booking_handler,
    get_current_user,
    get_delete_booking_handler,
    get_list_bookings_handler,
    get_mailer,
    get_update_booking_handler,
    require_administrator,
)
from app.domain.entities import Attendance, BookingScope, BookingStatus, User
from app.handlers.bookings import (
    CancelBookingHandler,
    CreateBookingHandler,
    DeleteBookingHandler,
    GetBookingHandler,
    ListBookingsHandler,
    RespondAttendanceHandler,
    UpdateBookingHandler,
)
from app.handlers.notifications import BookingNotifier
from app.schemas.auth import AuthenticationErrorResponse, ValidationErrorResponse
from app.schemas.bookings import (
    AttendanceRequest,
    BookingEnvelope,
    BookingListResponse,
    BookingResponse,
    CreateBookingRequest,
    UpdateBookingRequest,
)
from app.schemas.members import MemberErrorResponse as ErrorResponse
from app.schemas.members import PaginationMeta

router = APIRouter(
    prefix="/api/v1/bookings",
    tags=["US06 — Agenda das quadras"],
    responses={
        401: {
            "model": AuthenticationErrorResponse,
            "description": "Sessão ausente, inválida, expirada ou revogada",
            "headers": {"WWW-Authenticate": {"schema": {"type": "string"}, "example": "Bearer"}},
        },
        422: {"model": ValidationErrorResponse, "description": "Dados inválidos"},
    },
)
CurrentUser = Annotated[User, Depends(get_current_user)]
Notifier = Annotated[BookingNotifier, Depends(get_booking_notifier)]
MailerDependency = Annotated[Mailer, Depends(get_mailer)]
BookingId = Annotated[int, Path(ge=1, le=9223372036854775807)]
not_found = {
    "model": ErrorResponse,
    "description": "Reserva inexistente ou de outra pessoa (ou quadra inexistente, ao criar)",
}
conflict = {
    "model": ErrorResponse,
    "description": (
        "Horário já reservado sem join_waitlist, pedido duplicado da mesma conta, "
        "ou reserva cancelada/que já começou"
    ),
}
not_owner = {"model": ErrorResponse, "description": "Somente quem reservou ou um admin altera"}


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=BookingEnvelope,
    summary="Pedir reserva",
    description=(
        "Reserva de 60 ou 90 minutos, começando em hora cheia ou meia hora. Horário livre: "
        "status confirmed. Horário ocupado: 409, ou status waitlisted com join_waitlist=true. "
        "Quando a reserva confirmada é cancelada, o próximo pedido da fila (ordem de "
        "requested_at) é confirmado automaticamente. Quem reserva entra na lista de jogadores."
    ),
    responses={404: not_found, 409: conflict},
)
def create_booking(
    payload: CreateBookingRequest,
    user: CurrentUser,
    handler: Annotated[CreateBookingHandler, Depends(get_create_booking_handler)],
    notifier: Notifier,
    mailer: MailerDependency,
    background: BackgroundTasks,
) -> BookingEnvelope:
    booking = handler.handle(
        user,
        CreateBookingData(
            court_id=payload.court_id,
            starts_at=payload.starts_at,
            duration_minutes=payload.duration_minutes,
            player_ids=tuple(payload.player_ids),
            join_waitlist=payload.join_waitlist,
        ),
    )
    background.add_task(send_all, mailer, notifier.created(booking))
    return BookingEnvelope(data=BookingResponse.for_viewer(booking, user))


@router.get(
    "",
    response_model=BookingListResponse,
    summary="Listar reservas",
    description=(
        "Conta comum: reservas que fez ou em que joga. Admin: todas. "
        "starts_from/starts_to filtram pelo início (intervalo [starts_from, starts_to))."
    ),
)
def list_bookings(
    user: CurrentUser,
    handler: Annotated[ListBookingsHandler, Depends(get_list_bookings_handler)],
    page: Annotated[int, Query(ge=1, le=2147483647)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    court_id: Annotated[int | None, Query(ge=1, le=9223372036854775807)] = None,
    status_filter: Annotated[BookingStatus | None, Query(alias="status")] = None,
    starts_from: Annotated[AwareDatetime | None, Query()] = None,
    starts_to: Annotated[AwareDatetime | None, Query()] = None,
    scope: Annotated[
        BookingScope | None,
        Query(
            description=(
                "upcoming: confirmadas que não terminaram (mais próxima primeiro). "
                "past: canceladas e confirmadas que já terminaram (mais recente primeiro)."
            )
        ),
    ] = None,
    only_mine: Annotated[
        bool, Query(description="Para admin: só as reservas em que organiza ou joga.")
    ] = False,
) -> BookingListResponse:
    result = handler.handle(
        user,
        BookingFilters(
            court_id=court_id,
            status=status_filter,
            starts_from=starts_from,
            starts_to=starts_to,
            scope=scope,
            visible_to=user.id if only_mine else None,
        ),
        page=page,
        page_size=page_size,
    )
    return BookingListResponse(
        data=[BookingResponse.for_viewer(booking, user) for booking in result.items],
        meta=PaginationMeta(
            page=result.page,
            page_size=result.page_size,
            total=result.total,
            total_pages=(result.total + result.page_size - 1) // result.page_size,
        ),
    )


@router.get(
    "/{booking_id}",
    response_model=BookingEnvelope,
    summary="Consultar reserva",
    responses={404: not_found},
)
def get_booking(
    booking_id: BookingId,
    user: CurrentUser,
    handler: Annotated[GetBookingHandler, Depends(get_booking_handler)],
) -> BookingEnvelope:
    return BookingEnvelope(data=BookingResponse.for_viewer(handler.handle(user, booking_id), user))


@router.patch(
    "/{booking_id}",
    response_model=BookingEnvelope,
    summary="Trocar jogadores ou remarcar",
    description=(
        "Atualiza player_ids, a quadra e/ou o horário. Um novo horário conta como novo "
        "pedido: confirmado se estiver livre; ocupado, 409 ou fila com join_waitlist=true. "
        "Os convidados voltam a pending para confirmar o novo horário. "
        "O horário antigo liberado vai para o próximo da fila."
    ),
    responses={403: not_owner, 404: not_found, 409: conflict},
)
def update_booking(
    booking_id: BookingId,
    payload: UpdateBookingRequest,
    user: CurrentUser,
    handler: Annotated[UpdateBookingHandler, Depends(get_update_booking_handler)],
    notifier: Notifier,
    mailer: MailerDependency,
    background: BackgroundTasks,
) -> BookingEnvelope:
    booking = handler.handle(
        user,
        booking_id,
        UpdateBookingData(
            court_id=payload.court_id,
            starts_at=payload.starts_at,
            duration_minutes=payload.duration_minutes,
            player_ids=tuple(payload.player_ids) if payload.player_ids is not None else None,
            join_waitlist=payload.join_waitlist,
        ),
    )
    emails = notifier.rescheduled(booking, user) if handler.rescheduled else []
    if not handler.rescheduled:
        emails += notifier.invited(booking, handler.added_players)
    emails += notifier.promoted(handler.promoted)
    background.add_task(send_all, mailer, emails)
    return BookingEnvelope(data=BookingResponse.for_viewer(booking, user))


@router.post(
    "/{booking_id}/cancel",
    response_model=BookingEnvelope,
    summary="Cancelar reserva ou sair da fila",
    description=(
        "Marca como cancelled e mantém no histórico. Se a reserva estava confirmada, o próximo "
        "da fila para o horário fica com ela."
    ),
    responses={403: not_owner, 404: not_found, 409: conflict},
)
def cancel_booking(
    booking_id: BookingId,
    user: CurrentUser,
    handler: Annotated[CancelBookingHandler, Depends(get_cancel_booking_handler)],
    notifier: Notifier,
    mailer: MailerDependency,
    background: BackgroundTasks,
) -> BookingEnvelope:
    booking = handler.handle(user, booking_id)
    emails = notifier.cancelled(handler.removed, user) if handler.removed else []
    background.add_task(send_all, mailer, emails + notifier.promoted(handler.promoted))
    return BookingEnvelope(data=BookingResponse.for_viewer(booking, user))


@router.delete(
    "/{booking_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Excluir reserva (admin)",
    description="Remove o registro definitivamente. Para o usuário, use /cancel.",
    responses={
        403: {"model": ErrorResponse, "description": "Conta sem permissão de administrador"},
        404: not_found,
    },
)
def delete_booking(
    booking_id: BookingId,
    user: Annotated[User, Depends(require_administrator)],
    handler: Annotated[DeleteBookingHandler, Depends(get_delete_booking_handler)],
    notifier: Notifier,
    mailer: MailerDependency,
    background: BackgroundTasks,
) -> Response:
    handler.handle(user, booking_id)
    emails = notifier.cancelled(handler.removed, user) if handler.removed else []
    background.add_task(send_all, mailer, emails + notifier.promoted(handler.promoted))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/{booking_id}/attendance",
    response_model=BookingEnvelope,
    summary="Confirmar ou recusar presença",
    description="Para convidados da partida. Quem reservou já está confirmado (403).",
    responses={
        403: {"model": ErrorResponse, "description": "Quem reservou não responde presença"},
        404: not_found,
        409: {"model": ErrorResponse, "description": "Reserva cancelada ou que já começou"},
    },
)
def respond_attendance(
    booking_id: BookingId,
    payload: AttendanceRequest,
    user: CurrentUser,
    handler: Annotated[RespondAttendanceHandler, Depends(get_attendance_handler)],
) -> BookingEnvelope:
    booking = handler.handle(user, booking_id, Attendance(payload.response))
    return BookingEnvelope(data=BookingResponse.for_viewer(booking, user))
