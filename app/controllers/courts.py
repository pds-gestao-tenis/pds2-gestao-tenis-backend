from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Path, Query, Response, status

from app.core.mailer import Mailer, send_all
from app.data.courts import CreateCourtData, MaintenanceData, UpdateCourtData
from app.dependencies import (
    get_add_maintenance_handler,
    get_booking_notifier,
    get_court_handler,
    get_create_court_handler,
    get_current_user,
    get_delete_court_handler,
    get_list_courts_handler,
    get_mailer,
    get_remove_maintenance_handler,
    get_update_court_handler,
    require_administrator,
)
from app.domain.entities import User
from app.handlers.courts import (
    AddMaintenanceHandler,
    CreateCourtHandler,
    DeleteCourtHandler,
    GetCourtHandler,
    ListCourtsHandler,
    RemoveMaintenanceHandler,
    UpdateCourtHandler,
)
from app.handlers.notifications import BookingNotifier
from app.schemas.auth import AuthenticationErrorResponse, ValidationErrorResponse
from app.schemas.courts import (
    CourtEnvelope,
    CourtListResponse,
    CourtResponse,
    CreateCourtRequest,
    MaintenanceRequest,
    UpdateCourtRequest,
)
from app.schemas.members import MemberErrorResponse as ErrorResponse
from app.schemas.members import PaginationMeta

router = APIRouter(
    prefix="/api/v1/courts",
    tags=["US04 — Quadras"],
    dependencies=[Depends(get_current_user)],
    responses={
        401: {
            "model": AuthenticationErrorResponse,
            "description": "Sessão ausente, inválida, expirada ou revogada",
            "headers": {"WWW-Authenticate": {"schema": {"type": "string"}, "example": "Bearer"}},
        },
        422: {"model": ValidationErrorResponse, "description": "Dados inválidos"},
    },
)
admin_only = [Depends(require_administrator)]
forbidden = {"model": ErrorResponse, "description": "Conta sem permissão de administrador"}
not_found = {"model": ErrorResponse, "description": "Quadra não encontrada"}
duplicate = {"model": ValidationErrorResponse, "description": "Já existe quadra com este nome"}
CourtId = Annotated[int, Path(ge=1, le=9223372036854775807)]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=CourtEnvelope,
    summary="Cadastrar quadra (admin)",
    dependencies=admin_only,
    responses={403: forbidden, 409: duplicate},
)
def create_court(
    payload: CreateCourtRequest,
    handler: Annotated[CreateCourtHandler, Depends(get_create_court_handler)],
) -> CourtEnvelope:
    court = handler.handle(
        CreateCourtData(
            payload.name,
            payload.address,
            payload.size_m2,
            payload.max_players,
            payload.hourly_price,
            payload.surface,
            payload.covered,
        )
    )
    return CourtEnvelope(data=CourtResponse.model_validate(court))


@router.get(
    "",
    response_model=CourtListResponse,
    summary="Listar quadras",
    description="Disponível para qualquer conta autenticada. Filtra por nome com q.",
)
def list_courts(
    handler: Annotated[ListCourtsHandler, Depends(get_list_courts_handler)],
    page: Annotated[int, Query(ge=1, le=2147483647)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    q: Annotated[str | None, Query(max_length=120)] = None,
) -> CourtListResponse:
    result = handler.handle(page=page, page_size=page_size, search=q.strip() if q else None)
    return CourtListResponse(
        data=[CourtResponse.model_validate(court) for court in result.items],
        meta=PaginationMeta(
            page=result.page,
            page_size=result.page_size,
            total=result.total,
            total_pages=(result.total + result.page_size - 1) // result.page_size,
        ),
    )


@router.get(
    "/{court_id}",
    response_model=CourtEnvelope,
    summary="Consultar quadra",
    responses={404: not_found},
)
def get_court(
    court_id: CourtId,
    handler: Annotated[GetCourtHandler, Depends(get_court_handler)],
) -> CourtEnvelope:
    return CourtEnvelope(data=CourtResponse.model_validate(handler.handle(court_id)))


@router.patch(
    "/{court_id}",
    response_model=CourtEnvelope,
    summary="Editar quadra (admin)",
    description="Atualiza somente os campos informados.",
    dependencies=admin_only,
    responses={403: forbidden, 404: not_found, 409: duplicate},
)
def update_court(
    court_id: CourtId,
    payload: UpdateCourtRequest,
    handler: Annotated[UpdateCourtHandler, Depends(get_update_court_handler)],
) -> CourtEnvelope:
    court = handler.handle(
        court_id,
        UpdateCourtData(
            name=payload.name,
            address=payload.address,
            size_m2=payload.size_m2,
            max_players=payload.max_players,
            hourly_price=payload.hourly_price,
            surface=payload.surface,
            covered=payload.covered,
        ),
    )
    return CourtEnvelope(data=CourtResponse.model_validate(court))


@router.delete(
    "/{court_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Excluir quadra (admin)",
    description=(
        "Exclui a quadra e o histórico de reservas dela. Recusada (409) enquanto houver "
        "reservas confirmadas ou pedidos na fila que ainda não terminaram."
    ),
    dependencies=admin_only,
    responses={
        403: forbidden,
        404: not_found,
        409: {"model": ErrorResponse, "description": "Quadra com reservas futuras"},
    },
)
def delete_court(
    court_id: CourtId,
    handler: Annotated[DeleteCourtHandler, Depends(get_delete_court_handler)],
) -> Response:
    handler.handle(court_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


MaintenanceId = Annotated[int, Path(ge=1, le=9223372036854775807)]


@router.post(
    "/{court_id}/maintenance",
    status_code=status.HTTP_201_CREATED,
    response_model=CourtEnvelope,
    summary="Agendar manutenção (admin)",
    description=(
        "Bloqueia o período para novas reservas. Se houver reservas ou pedidos na fila que "
        "ainda não começaram no período, responde 409; com cancel_bookings=true, cancela-os."
    ),
    dependencies=admin_only,
    responses={
        403: forbidden,
        404: not_found,
        409: {"model": ValidationErrorResponse, "description": "Há reservas no período"},
    },
)
def add_maintenance(
    court_id: CourtId,
    payload: MaintenanceRequest,
    handler: Annotated[AddMaintenanceHandler, Depends(get_add_maintenance_handler)],
    user: Annotated[User, Depends(require_administrator)],
    notifier: Annotated[BookingNotifier, Depends(get_booking_notifier)],
    mailer: Annotated[Mailer, Depends(get_mailer)],
    background: BackgroundTasks,
) -> CourtEnvelope:
    court = handler.handle(
        court_id,
        MaintenanceData(
            payload.starts_at,
            payload.ends_at,
            payload.reason,
            payload.cancel_bookings,
            payload.kind,
        ),
    )
    # US17: quem tinha reserva no período é avisado do cancelamento.
    emails = []
    for booking_id in handler.cancelled:
        booking = notifier.bookings.get(booking_id)
        if booking is not None:
            emails += notifier.cancelled(
                booking, user, reason=f"período bloqueado na quadra ({payload.reason})"
            )
    background.add_task(send_all, mailer, emails + notifier.promoted(handler.promoted))
    return CourtEnvelope(data=CourtResponse.model_validate(court))


@router.delete(
    "/{court_id}/maintenance/{maintenance_id}",
    response_model=CourtEnvelope,
    summary="Remover manutenção (admin)",
    description="Libera o período. Reservas canceladas pela manutenção não são restauradas.",
    dependencies=admin_only,
    responses={
        403: forbidden,
        404: {"model": ErrorResponse, "description": "Quadra ou manutenção não encontrada"},
    },
)
def remove_maintenance(
    court_id: CourtId,
    maintenance_id: MaintenanceId,
    handler: Annotated[RemoveMaintenanceHandler, Depends(get_remove_maintenance_handler)],
) -> CourtEnvelope:
    return CourtEnvelope(
        data=CourtResponse.model_validate(handler.handle(court_id, maintenance_id))
    )
