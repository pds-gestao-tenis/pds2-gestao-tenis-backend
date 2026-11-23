"""Taxas e pagamentos dos membros (US19-US22).

- A administração lança taxas, registra pagamentos e vê quem está com pendências.
- O jogador vê as taxas do membro com o mesmo e-mail da conta e pode pagar pelo sistema.

O pagamento pelo sistema (US22) é registrado na hora, sem gateway: o ponto de integração com um
provedor de pagamentos é PayOwnFeeHandler.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.data.fees import CreateFeeData, FeeFilters, PaymentData, UpdateFeeData
from app.domain.entities import (
    Fee,
    FeeMember,
    FeePage,
    FeeStatus,
    PaidVia,
    PaymentMethod,
    PendingMember,
    User,
)
from app.domain.exceptions import FeeAlreadyPaidError, FeeNotFoundError, MemberNotFoundError
from app.repositories.contracts import FeeRepository


def utcnow() -> datetime:
    return datetime.now(UTC)


class _FeeHandler:
    def __init__(
        self, fees: FeeRepository, zone: ZoneInfo, clock: Callable[[], datetime] = utcnow
    ) -> None:
        self.fees = fees
        self.zone = zone
        self.clock = clock

    def today(self) -> date:
        return self.clock().astimezone(self.zone).date()

    def _pending(self, fee_id: int) -> Fee:
        fee = self.fees.get(fee_id, lock=True)
        if fee is None:
            raise FeeNotFoundError
        if fee.status is FeeStatus.PAID:
            raise FeeAlreadyPaidError
        return fee


class CreateFeeHandler(_FeeHandler):
    def handle(self, data: CreateFeeData) -> Fee:
        if not self.fees.member_exists(data.member_id):
            raise MemberNotFoundError
        return self.fees.create(data)


class ListFeesHandler(_FeeHandler):
    def handle(
        self, filters: FeeFilters, *, overdue: bool = False, page: int = 1, page_size: int = 20
    ) -> FeePage:
        if overdue:
            filters = FeeFilters(member_id=filters.member_id, due_before=self.today())
        return self.fees.list(filters, page=page, page_size=page_size)


class UpdateFeeHandler(_FeeHandler):
    def handle(self, fee_id: int, data: UpdateFeeData) -> Fee:
        self._pending(fee_id)
        return self.fees.update(fee_id, data)


class DeleteFeeHandler(_FeeHandler):
    def handle(self, fee_id: int) -> None:
        self._pending(fee_id)
        self.fees.delete(fee_id)


class RegisterPaymentHandler(_FeeHandler):
    """US19: a administração registra um pagamento recebido (dinheiro, Pix, cartão...)."""

    def handle(self, fee_id: int, method: PaymentMethod, paid_at: datetime | None) -> Fee:
        self._pending(fee_id)
        return self.fees.pay(
            fee_id,
            PaymentData(method=method, paid_at=paid_at or self.clock(), paid_via=PaidVia.ADMIN),
        )


class PendingMembersHandler(_FeeHandler):
    """US21: quem tem pagamentos pendentes."""

    def handle(self) -> list[PendingMember]:
        return list(self.fees.pending_members(self.today()))


@dataclass(frozen=True, slots=True)
class MyFees:
    member: FeeMember | None
    fees: list[Fee]
    pending_total: Decimal
    paid_total: Decimal


class MyFeesHandler(_FeeHandler):
    """US20: taxas pagas e pendentes do próprio jogador."""

    def handle(self, user: User) -> MyFees:
        member = self.fees.member_by_email(user.email)
        fees = list(self.fees.for_member(member.id)) if member else []
        return MyFees(
            member=member,
            fees=fees,
            pending_total=sum(
                (fee.amount for fee in fees if fee.status is FeeStatus.PENDING), Decimal("0")
            ),
            paid_total=sum(
                (fee.amount for fee in fees if fee.status is FeeStatus.PAID), Decimal("0")
            ),
        )


class PayOwnFeeHandler(_FeeHandler):
    """US22: o jogador paga uma taxa própria pelo sistema.

    Sem gateway configurado, o pagamento é aprovado na hora. Para integrar um provedor (Pix,
    cartão), crie a cobrança aqui e confirme a taxa no retorno (webhook) do provedor.
    """

    def handle(self, user: User, fee_id: int, method: PaymentMethod) -> Fee:
        member = self.fees.member_by_email(user.email)
        fee = self.fees.get(fee_id, lock=True)
        # Taxa de outro membro: 404, sem revelar que existe.
        if fee is None or member is None or fee.member.id != member.id:
            raise FeeNotFoundError
        if fee.status is FeeStatus.PAID:
            raise FeeAlreadyPaidError
        return self.fees.pay(
            fee_id, PaymentData(method=method, paid_at=self.clock(), paid_via=PaidVia.ONLINE)
        )
