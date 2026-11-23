from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.dependencies import get_occupancy_handler, require_administrator
from app.handlers.reports import OccupancyReportHandler, Usage
from app.schemas.auth import AuthenticationErrorResponse, ValidationErrorResponse
from app.schemas.members import MemberErrorResponse as ErrorResponse

router = APIRouter(
    prefix="/api/v1/reports",
    tags=["US30 — Indicadores"],
    dependencies=[Depends(require_administrator)],
    responses={
        401: {"model": AuthenticationErrorResponse, "description": "Sessão inválida"},
        403: {"model": ErrorResponse, "description": "Conta sem permissão de administrador"},
        422: {"model": ValidationErrorResponse, "description": "Período inválido"},
    },
)


class UsageResponse(BaseModel):
    booked_hours: float
    available_hours: float
    occupancy_rate: float = Field(description="De 0 a 1")

    @classmethod
    def of(cls, usage: Usage) -> "UsageResponse":
        return cls(
            booked_hours=round(usage.booked_minutes / 60, 2),
            available_hours=round(usage.available_minutes / 60, 2),
            occupancy_rate=usage.rate,
        )


class CourtRef(BaseModel):
    id: int
    name: str


class CourtOccupancy(UsageResponse):
    court: CourtRef
    blocked_hours: float
    bookings: int


class WeekdayOccupancy(UsageResponse):
    weekday: int = Field(description="0 = segunda-feira ... 6 = domingo")


class HourOccupancy(UsageResponse):
    hour: int = Field(description="Início do bloco de uma hora, no fuso do clube")


class Totals(UsageResponse):
    bookings: int
    cancelled: int


class OccupancyData(BaseModel):
    period: dict[str, date | int]
    totals: Totals
    courts: list[CourtOccupancy]
    by_weekday: list[WeekdayOccupancy]
    by_hour: list[HourOccupancy]


class OccupancyEnvelope(BaseModel):
    data: OccupancyData


@router.get(
    "/occupancy",
    response_model=OccupancyEnvelope,
    summary="Ocupação das quadras (admin)",
    description=(
        "Horas reservadas (confirmadas) sobre horas disponíveis (07:00-22:00 menos bloqueios), "
        "por quadra, dia da semana e hora. Padrão: últimos 30 dias até hoje. Máximo de 92 dias."
    ),
)
def occupancy(
    handler: Annotated[OccupancyReportHandler, Depends(get_occupancy_handler)],
    starts_on: Annotated[date | None, Query(alias="from")] = None,
    ends_on: Annotated[date | None, Query(alias="to")] = None,
) -> OccupancyEnvelope:
    report = handler.handle(starts_on, ends_on)
    days = (report.ends_on - report.starts_on).days + 1
    return OccupancyEnvelope(
        data=OccupancyData(
            period={"from": report.starts_on, "to": report.ends_on, "days": days},
            totals=Totals(
                **UsageResponse.of(report.total).model_dump(),
                bookings=report.bookings,
                cancelled=report.cancelled,
            ),
            courts=[
                CourtOccupancy(
                    **UsageResponse.of(item.usage).model_dump(),
                    court=CourtRef(id=item.court.id, name=item.court.name),
                    blocked_hours=round(item.blocked_minutes / 60, 2),
                    bookings=item.bookings,
                )
                for item in report.courts
            ],
            by_weekday=[
                WeekdayOccupancy(**UsageResponse.of(usage).model_dump(), weekday=day)
                for day, usage in report.by_weekday.items()
            ],
            by_hour=[
                HourOccupancy(**UsageResponse.of(usage).model_dump(), hour=hour)
                for hour, usage in report.by_hour.items()
            ],
        )
    )
