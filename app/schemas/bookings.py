from datetime import UTC, date, datetime
from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from app.domain.entities import Attendance, Booking, BookingStatus, SlotStatus, User
from app.schemas.courts import CourtResponse
from app.schemas.members import PaginationMeta

MAX_ID = 9223372036854775807
Duration = Literal[60, 90]
PlayerIds = Annotated[
    list[Annotated[int, Field(ge=1, le=MAX_ID)]],
    Field(max_length=50, description="Contas que vão jogar. Quem reserva entra automaticamente."),
]


def aligned_start(value: datetime) -> datetime:
    if value.second or value.microsecond or value.minute not in (0, 30):
        raise ValueError("O horário deve começar em hora cheia ou meia hora, como 19:00 ou 19:30.")
    return value.astimezone(UTC)


class CreateBookingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    court_id: int = Field(ge=1, le=MAX_ID)
    starts_at: AwareDatetime = Field(
        strict=False,
        description="Início com fuso horário, em hora cheia ou meia hora.",
        examples=["2026-11-20T19:00:00-03:00"],
    )
    duration_minutes: Duration = Field(default=60, description="60 ou 90 minutos.")
    player_ids: PlayerIds = []
    join_waitlist: bool = Field(
        default=False,
        description="Se o horário já estiver reservado, entra na fila em vez de recusar.",
    )

    @field_validator("starts_at")
    @classmethod
    def validate_start(cls, value: datetime) -> datetime:
        return aligned_start(value)


class UpdateBookingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    court_id: int | None = Field(default=None, ge=1, le=MAX_ID, description="Trocar de quadra.")
    starts_at: AwareDatetime | None = Field(
        default=None, strict=False, examples=["2026-11-20T19:30:00-03:00"]
    )
    duration_minutes: Duration | None = None
    player_ids: PlayerIds | None = None
    join_waitlist: bool = Field(
        default=False,
        description="Ao remarcar para um horário ocupado, entra na fila em vez de recusar.",
    )

    @field_validator("court_id", "starts_at", "duration_minutes", "player_ids")
    @classmethod
    def reject_explicit_null(cls, value):
        if value is None:
            raise ValueError("Este campo não pode ser nulo quando informado.")
        return value

    @field_validator("starts_at")
    @classmethod
    def validate_start(cls, value: datetime) -> datetime:
        return aligned_start(value)

    @model_validator(mode="after")
    def require_changes(self) -> Self:
        if not self.model_fields_set & {"court_id", "starts_at", "duration_minutes", "player_ids"}:
            raise ValueError(
                "Informe court_id, starts_at, duration_minutes ou player_ids para atualizar."
            )
        return self


class PersonResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class PlayerResponse(PersonResponse):
    attendance: Attendance = Field(description="Quem reservou já começa confirmado.")


class AttendanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    response: Literal["confirmed", "declined"]


class BookingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    court: PersonResponse
    organizer: PersonResponse
    players: list[PlayerResponse]
    starts_at: datetime
    ends_at: datetime
    status: BookingStatus
    requested_at: datetime
    cancelled_at: datetime | None
    waitlist_position: int | None = Field(
        description="Posição na fila de espera do horário; null quando não está na fila."
    )
    my_role: Literal["organizer", "participant"] | None = Field(
        default=None,
        description="Papel da conta autenticada; null para admin vendo reserva de outra pessoa.",
    )

    @classmethod
    def for_viewer(cls, booking: Booking, viewer: User) -> "BookingResponse":
        if booking.organizer.id == viewer.id:
            role = "organizer"
        elif any(player.id == viewer.id for player in booking.players):
            role = "participant"
        else:
            role = None
        return cls.model_validate(booking).model_copy(update={"my_role": role})

    @computed_field
    @property
    def duration_minutes(self) -> int:
        return int((self.ends_at - self.starts_at).total_seconds() // 60)


class BookingEnvelope(BaseModel):
    data: BookingResponse


class BookingListResponse(BaseModel):
    data: list[BookingResponse]
    meta: PaginationMeta


class SlotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    court_id: int
    starts_at: datetime
    ends_at: datetime
    status: SlotStatus
    booking_id: int | None = Field(description="Só quando o horário é seu (status mine).")
    waitlist_size: int
    waitlist_entry_id: int | None = Field(
        description="Seu pedido na fila desse horário (id da reserva), se houver."
    )


class ScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: date
    courts: list[CourtResponse]
    slots: list[SlotResponse]


class ScheduleEnvelope(BaseModel):
    data: ScheduleResponse


class PlayerListResponse(BaseModel):
    data: list[PersonResponse]
