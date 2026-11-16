from datetime import datetime
from decimal import Decimal
from typing import Annotated, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    ValidationInfo,
    field_validator,
    model_validator,
)

from app.domain.entities import Surface
from app.schemas.members import PaginationMeta

# Aceita número ou texto ("120.50") e responde como número JSON.
AsNumber = PlainSerializer(float, return_type=float, when_used="json")
SizeM2 = Annotated[Decimal, Field(strict=False, gt=0, max_digits=8, decimal_places=2), AsNumber]
Price = Annotated[Decimal, Field(strict=False, ge=0, max_digits=10, decimal_places=2), AsNumber]
MaxPlayers = Annotated[int, Field(ge=1, le=50)]
SurfaceField = Annotated[
    Surface, Field(strict=False, description="Piso: clay, hard, grass ou synthetic.")
]


class CourtInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator("name", "address", mode="before", check_fields=False)
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("surface", mode="before", check_fields=False)
    @classmethod
    def validate_surface(cls, value: object) -> object:
        if value is not None and value not in {item.value for item in Surface}:
            raise ValueError("Escolha um piso válido: clay, hard, grass ou synthetic.")
        return value


class CreateCourtRequest(CourtInput):
    name: str = Field(min_length=1, max_length=120, examples=["Quadra 1"])
    address: str = Field(
        min_length=1, max_length=255, examples=["Rua das Palmeiras, 100 — Setor A"]
    )
    size_m2: SizeM2 = Field(description="Área em metros quadrados.", examples=[260.76])
    max_players: MaxPlayers = Field(
        description="Máximo de jogadores por partida, contando quem reserva.", examples=[4]
    )
    hourly_price: Price = Field(description="Preço da hora, em reais.", examples=[120.0])
    surface: SurfaceField
    covered: bool = Field(description="Se a quadra é coberta.")


class UpdateCourtRequest(CourtInput):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    address: str | None = Field(default=None, min_length=1, max_length=255)
    size_m2: SizeM2 | None = None
    max_players: MaxPlayers | None = None
    hourly_price: Price | None = None
    surface: SurfaceField | None = None
    covered: bool | None = None

    @field_validator(
        "name", "address", "size_m2", "max_players", "hourly_price", "surface", "covered"
    )
    @classmethod
    def reject_explicit_null(cls, value):
        if value is None:
            raise ValueError("Este campo não pode ser nulo quando informado.")
        return value

    @model_validator(mode="after")
    def require_changes(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Informe ao menos um campo para atualizar.")
        return self


class MaintenanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    starts_at: AwareDatetime = Field(strict=False, examples=["2026-11-20T08:00:00-03:00"])
    ends_at: AwareDatetime = Field(strict=False, examples=["2026-11-20T12:00:00-03:00"])
    reason: str = Field(min_length=1, max_length=200, examples=["Troca do saibro"])
    cancel_bookings: bool = Field(
        default=False,
        description="Cancela as reservas e pedidos na fila do período em vez de recusar (409).",
    )

    @field_validator("reason", mode="before")
    @classmethod
    def strip_reason(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("ends_at")
    @classmethod
    def after_start(cls, value: datetime, info: ValidationInfo) -> datetime:
        starts_at = info.data.get("starts_at")
        if starts_at is not None and value <= starts_at:
            raise ValueError("O fim precisa ser depois do início.")
        return value


class MaintenanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    starts_at: datetime
    ends_at: datetime
    reason: str


class CourtResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    address: str
    size_m2: Annotated[Decimal, AsNumber]
    max_players: int
    hourly_price: Annotated[Decimal, AsNumber]
    surface: Surface
    covered: bool
    maintenance: list[MaintenanceResponse] = Field(
        description="Manutenções que ainda não terminaram, em ordem de início."
    )
    created_at: datetime
    updated_at: datetime


class CourtEnvelope(BaseModel):
    data: CourtResponse


class CourtListResponse(BaseModel):
    data: list[CourtResponse]
    meta: PaginationMeta
