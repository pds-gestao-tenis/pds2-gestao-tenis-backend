"""US30: indicadores de ocupação das quadras.

Ocupação = horas reservadas (confirmadas) / horas disponíveis. Disponível é o horário de
funcionamento da agenda (FIRST_HOUR às LAST_HOUR + 1, no fuso do clube) menos os bloqueios de
manutenção ou evento. As contas são feitas em blocos de uma hora por quadra e dia.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.domain.entities import Person
from app.domain.exceptions import InvalidBookingError
from app.handlers.schedule import FIRST_HOUR, LAST_HOUR
from app.repositories.sqlalchemy_reports import Interval, SqlAlchemyReportRepository

MAX_DAYS = 92
HOURS = range(FIRST_HOUR, LAST_HOUR + 1)


@dataclass(frozen=True, slots=True)
class Usage:
    booked_minutes: int = 0
    available_minutes: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.booked_minutes + other.booked_minutes,
            self.available_minutes + other.available_minutes,
        )

    @property
    def rate(self) -> float:
        if not self.available_minutes:
            return 0.0
        return round(self.booked_minutes / self.available_minutes, 4)


@dataclass(frozen=True, slots=True)
class CourtUsage:
    court: Person
    usage: Usage
    blocked_minutes: int
    bookings: int


@dataclass(frozen=True, slots=True)
class OccupancyReport:
    starts_on: date
    ends_on: date
    total: Usage
    bookings: int
    cancelled: int
    courts: list[CourtUsage]
    by_weekday: dict[int, Usage]
    by_hour: dict[int, Usage]


def _overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> int:
    seconds = (min(a_end, b_end) - max(a_start, b_start)).total_seconds()
    return max(0, int(seconds // 60))


class OccupancyReportHandler:
    def __init__(self, reports: SqlAlchemyReportRepository, zone: ZoneInfo) -> None:
        self.reports = reports
        self.zone = zone

    def today(self) -> date:
        return datetime.now(UTC).astimezone(self.zone).date()

    def handle(self, starts_on: date | None, ends_on: date | None) -> OccupancyReport:
        ends_on = ends_on or self.today()
        starts_on = starts_on or ends_on - timedelta(days=29)
        if starts_on > ends_on:
            raise InvalidBookingError("from", "A data inicial deve ser anterior à final.")
        if (ends_on - starts_on).days + 1 > MAX_DAYS:
            raise InvalidBookingError("to", f"Escolha um período de até {MAX_DAYS} dias.")

        start = datetime.combine(starts_on, time(0), tzinfo=self.zone).astimezone(UTC)
        end = datetime.combine(ends_on + timedelta(days=1), time(0), tzinfo=self.zone).astimezone(
            UTC
        )
        courts = self.reports.courts()
        bookings = self.reports.confirmed_bookings(start, end)
        blocks = self.reports.blocks(start, end)

        by_court: dict[int, list[Interval]] = defaultdict(list)
        for item in bookings:
            by_court[item.court_id].append(item)
        blocks_by_court: dict[int, list[Interval]] = defaultdict(list)
        for item in blocks:
            blocks_by_court[item.court_id].append(item)

        by_weekday: dict[int, Usage] = {day: Usage() for day in range(7)}
        by_hour: dict[int, Usage] = {hour: Usage() for hour in HOURS}
        court_usage: list[CourtUsage] = []
        day = starts_on
        days = []
        while day <= ends_on:
            days.append(day)
            day += timedelta(days=1)

        for court in courts:
            usage = Usage()
            blocked_total = 0
            for day in days:
                for hour in HOURS:
                    slot_start = datetime.combine(day, time(hour), tzinfo=self.zone)
                    slot_end = slot_start + timedelta(hours=1)
                    blocked = min(
                        60,
                        sum(
                            _overlap(slot_start, slot_end, block.starts_at, block.ends_at)
                            for block in blocks_by_court[court.id]
                        ),
                    )
                    available = 60 - blocked
                    booked = min(
                        available,
                        sum(
                            _overlap(slot_start, slot_end, item.starts_at, item.ends_at)
                            for item in by_court[court.id]
                        ),
                    )
                    cell = Usage(booked, available)
                    usage = usage + cell
                    blocked_total += blocked
                    by_weekday[day.weekday()] = by_weekday[day.weekday()] + cell
                    by_hour[hour] = by_hour[hour] + cell
            court_usage.append(CourtUsage(court, usage, blocked_total, len(by_court[court.id])))

        total = sum((item.usage for item in court_usage), Usage())
        return OccupancyReport(
            starts_on=starts_on,
            ends_on=ends_on,
            total=total,
            bookings=len(bookings),
            cancelled=self.reports.cancelled_count(start, end),
            courts=sorted(court_usage, key=lambda item: (-item.usage.rate, item.court.name)),
            by_weekday=by_weekday,
            by_hour=by_hour,
        )
