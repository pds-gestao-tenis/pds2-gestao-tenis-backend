from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.entities import Fee, FeeMember, FeeStatus, PaidVia, PaymentMethod
from app.schemas.courts import AsNumber
from app.schemas.members import PaginationMeta

# Aceita número ou texto ("150.00") e responde como número JSON, como os preços das quadras.
Amount = Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=2, strict=False), AsNumber]
Money = Annotated[Decimal, AsNumber]


class FeeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator("description", mode="before", check_fields=False)
    @classmethod
    def strip(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class CreateFeeRequest(FeeInput):
    member_id: int = Field(ge=1, le=9223372036854775807)
    description: str = Field(min_length=1, max_length=120, examples=["Mensalidade de dezembro"])
    amount: Amount = Field(examples=["150.00"])
    due_date: date = Field(strict=False, examples=["2026-12-10"])


class UpdateFeeRequest(FeeInput):
    description: str | None = Field(default=None, min_length=1, max_length=120)
    amount: Amount | None = None
    due_date: Annotated[date, Field(strict=False)] | None = None

    @field_validator("description", "amount", "due_date")
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


class RegisterPaymentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: PaymentMethod = Field(description="cash, pix, card ou transfer")
    paid_at: AwareDatetime | None = Field(
        default=None, description="Quando foi pago; padrão: agora. Não pode ser no futuro."
    )

    @field_validator("paid_at")
    @classmethod
    def not_in_future(cls, value: datetime | None) -> datetime | None:
        if value is not None and value > datetime.now(UTC):
            raise ValueError("A data do pagamento não pode estar no futuro.")
        return value


class PayFeeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Literal["pix", "card"] = Field(description="Forma de pagamento pelo sistema")


class FeeMemberResponse(BaseModel):
    id: int
    name: str
    email: str

    @classmethod
    def of(cls, member: FeeMember) -> "FeeMemberResponse":
        return cls(id=member.id, name=member.name, email=member.email)


class FeeResponse(BaseModel):
    id: int
    member: FeeMemberResponse
    description: str
    amount: Money
    due_date: date
    status: FeeStatus
    overdue: bool = Field(description="Pendente com vencimento antes de hoje (fuso do clube)")
    paid_at: datetime | None
    payment_method: PaymentMethod | None
    paid_via: PaidVia | None = Field(description="admin: registrado pela administração")
    created_at: datetime

    @classmethod
    def of(cls, fee: Fee, today: date) -> "FeeResponse":
        return cls(
            id=fee.id,
            member=FeeMemberResponse.of(fee.member),
            description=fee.description,
            amount=fee.amount,
            due_date=fee.due_date,
            status=fee.status,
            overdue=fee.overdue(today),
            paid_at=fee.paid_at,
            payment_method=fee.payment_method,
            paid_via=fee.paid_via,
            created_at=fee.created_at,
        )


class FeeEnvelope(BaseModel):
    data: FeeResponse


class FeeListResponse(BaseModel):
    data: list[FeeResponse]
    meta: PaginationMeta


class PendingMemberResponse(BaseModel):
    member: FeeMemberResponse
    pending_count: int
    pending_total: Money
    overdue_count: int
    oldest_due_date: date


class PendingMembersResponse(BaseModel):
    data: list[PendingMemberResponse]


class MyFeesSummary(BaseModel):
    pending_total: Money
    paid_total: Money
    overdue_count: int


class MyFeesResponse(BaseModel):
    member: FeeMemberResponse | None = Field(
        description="Cadastro de membro com o mesmo e-mail da conta; null se não houver"
    )
    data: list[FeeResponse]
    summary: MyFeesSummary
