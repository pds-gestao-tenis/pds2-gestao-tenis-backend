from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.domain.entities import BlockKind, Surface


@dataclass(frozen=True, slots=True)
class CreateCourtData:
    name: str
    address: str
    size_m2: Decimal
    max_players: int
    hourly_price: Decimal
    surface: Surface
    covered: bool


@dataclass(frozen=True, slots=True)
class UpdateCourtData:
    name: str | None = None
    address: str | None = None
    size_m2: Decimal | None = None
    max_players: int | None = None
    hourly_price: Decimal | None = None
    surface: Surface | None = None
    covered: bool | None = None


@dataclass(frozen=True, slots=True)
class MaintenanceData:
    starts_at: datetime
    ends_at: datetime
    reason: str
    cancel_bookings: bool = False
    kind: BlockKind = BlockKind.MAINTENANCE
