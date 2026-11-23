from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from app.domain.entities import FeeStatus, PaidVia, PaymentMethod


@dataclass(frozen=True, slots=True)
class CreateFeeData:
    member_id: int
    description: str
    amount: Decimal
    due_date: date


@dataclass(frozen=True, slots=True)
class UpdateFeeData:
    description: str | None = None
    amount: Decimal | None = None
    due_date: date | None = None


@dataclass(frozen=True, slots=True)
class PaymentData:
    method: PaymentMethod
    paid_at: datetime
    paid_via: PaidVia


@dataclass(frozen=True, slots=True)
class FeeFilters:
    member_id: int | None = None
    status: FeeStatus | None = None
    # Só pendentes com vencimento antes desta data (atrasadas).
    due_before: date | None = None
