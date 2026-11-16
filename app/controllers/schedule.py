from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.dependencies import get_current_user, get_schedule_handler, get_search_players_handler
from app.domain.entities import User
from app.handlers.schedule import GetScheduleHandler, SearchPlayersHandler
from app.schemas.auth import AuthenticationErrorResponse, ValidationErrorResponse
from app.schemas.bookings import (
    PersonResponse,
    PlayerListResponse,
    ScheduleEnvelope,
    ScheduleResponse,
)

router = APIRouter(
    prefix="/api/v1",
    tags=["Agenda das quadras"],
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


@router.get(
    "/schedule",
    response_model=ScheduleEnvelope,
    summary="Agenda de um dia",
    description=(
        "Todas as quadras em blocos de 1 hora, das 07:00 às 22:00 no fuso do clube. Cada bloco "
        "diz se está livre, ocupado, em manutenção ou é seu, e quantos pedidos há na fila. "
        "Não expõe quem reservou os horários de outras pessoas."
    ),
)
def get_schedule(
    user: CurrentUser,
    handler: Annotated[GetScheduleHandler, Depends(get_schedule_handler)],
    day: Annotated[date, Query(alias="date", description="Dia no formato AAAA-MM-DD.")],
) -> ScheduleEnvelope:
    return ScheduleEnvelope(data=ScheduleResponse.model_validate(handler.handle(user, day)))


@router.get(
    "/players",
    response_model=PlayerListResponse,
    summary="Buscar jogadores para convidar",
    description="Contas cujo nome contém q (até 10). A própria conta não aparece.",
)
def search_players(
    user: CurrentUser,
    handler: Annotated[SearchPlayersHandler, Depends(get_search_players_handler)],
    q: Annotated[str, Query(min_length=2, max_length=60)],
) -> PlayerListResponse:
    return PlayerListResponse(
        data=[PersonResponse.model_validate(item) for item in handler.handle(user, q)]
    )
