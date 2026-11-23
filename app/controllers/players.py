from typing import Annotated

from fastapi import APIRouter, Depends

from app.dependencies import (
    get_current_user,
    get_player_profile_handler,
    get_suggest_partners_handler,
    get_update_player_profile_handler,
)
from app.domain.entities import Availability, User
from app.handlers.players import (
    GetPlayerProfileHandler,
    SuggestPartnersHandler,
    UpdatePlayerProfileHandler,
)
from app.schemas.auth import AuthenticationErrorResponse, ValidationErrorResponse
from app.schemas.members import MemberErrorResponse as ErrorResponse
from app.schemas.players import (
    PartnerListResponse,
    PartnerResponse,
    ProfileEnvelope,
    ProfileResponse,
    UpdateProfileRequest,
)

router = APIRouter(
    prefix="/api/v1/players",
    tags=["US23-US24 — Perfil de jogo e parceiros"],
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


@router.get("/me/profile", response_model=ProfileEnvelope, summary="Meu nível e disponibilidade")
def get_profile(
    user: CurrentUser,
    handler: Annotated[GetPlayerProfileHandler, Depends(get_player_profile_handler)],
) -> ProfileEnvelope:
    return ProfileEnvelope(data=ProfileResponse.of(handler.handle(user)))


@router.put(
    "/me/profile",
    response_model=ProfileEnvelope,
    summary="Informar nível e disponibilidade",
    description="Substitui o nível e a lista de dias/períodos em que o jogador costuma jogar.",
)
def update_profile(
    payload: UpdateProfileRequest,
    user: CurrentUser,
    handler: Annotated[UpdatePlayerProfileHandler, Depends(get_update_player_profile_handler)],
) -> ProfileEnvelope:
    profile = handler.handle(
        user,
        payload.skill_level,
        {Availability(item.weekday, item.period) for item in payload.availability},
    )
    return ProfileEnvelope(data=ProfileResponse.of(profile))


@router.get(
    "/partners",
    response_model=PartnerListResponse,
    summary="Jogadores com nível e disponibilidade semelhantes",
    description=(
        "Jogadores de nível igual ou vizinho. Se a conta informou disponibilidade, só entram os "
        "que têm ao menos um dia/período em comum, com mais horários em comum primeiro."
    ),
    responses={
        409: {"model": ErrorResponse, "description": "Nível da própria conta não informado"}
    },
)
def partners(
    user: CurrentUser,
    handler: Annotated[SuggestPartnersHandler, Depends(get_suggest_partners_handler)],
) -> PartnerListResponse:
    return PartnerListResponse(data=[PartnerResponse.of(item) for item in handler.handle(user)])
