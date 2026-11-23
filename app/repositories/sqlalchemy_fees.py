from collections.abc import Sequence
from datetime import date

from sqlalchemy import case, delete, func, select, update
from sqlalchemy.orm import Session

from app.data.fees import CreateFeeData, FeeFilters, PaymentData, UpdateFeeData
from app.db.models import MemberFeeModel, MemberModel
from app.domain.entities import (
    Fee,
    FeeMember,
    FeePage,
    FeeStatus,
    PaidVia,
    PaymentMethod,
    PendingMember,
)


class SqlAlchemyFeeRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def commit(self) -> None:
        self.session.commit()

    @staticmethod
    def _to_fee(record: MemberFeeModel, member: MemberModel) -> Fee:
        return Fee(
            id=record.id,
            member=FeeMember(member.id, member.name, member.email),
            description=record.description,
            amount=record.amount,
            due_date=record.due_date,
            status=FeeStatus(record.status),
            paid_at=record.paid_at,
            payment_method=PaymentMethod(record.payment_method) if record.payment_method else None,
            paid_via=PaidVia(record.paid_via) if record.paid_via else None,
            created_at=record.created_at,
        )

    def _select(self):
        return select(MemberFeeModel, MemberModel).join(
            MemberModel, MemberModel.id == MemberFeeModel.member_id
        )

    def member_exists(self, member_id: int) -> bool:
        return self.session.get(MemberModel, member_id) is not None

    def member_by_email(self, email: str) -> FeeMember | None:
        member = self.session.scalar(select(MemberModel).where(MemberModel.email == email.lower()))
        return FeeMember(member.id, member.name, member.email) if member else None

    def create(self, data: CreateFeeData) -> Fee:
        record = MemberFeeModel(
            member_id=data.member_id,
            description=data.description,
            amount=data.amount,
            due_date=data.due_date,
            status=FeeStatus.PENDING.value,
        )
        self.session.add(record)
        self.session.flush()
        fee = self.get(record.id)
        self.session.commit()
        assert fee is not None
        return fee

    def get(self, fee_id: int, *, lock: bool = False) -> Fee | None:
        query = self._select().where(MemberFeeModel.id == fee_id)
        if lock:
            query = query.with_for_update(of=MemberFeeModel)
        row = self.session.execute(query).first()
        return self._to_fee(*row) if row else None

    def list(self, filters: FeeFilters, *, page: int, page_size: int) -> FeePage:
        conditions = []
        if filters.member_id is not None:
            conditions.append(MemberFeeModel.member_id == filters.member_id)
        if filters.status is not None:
            conditions.append(MemberFeeModel.status == filters.status.value)
        if filters.due_before is not None:
            conditions.append(MemberFeeModel.status == FeeStatus.PENDING.value)
            conditions.append(MemberFeeModel.due_date < filters.due_before)
        total = self.session.scalar(
            select(func.count()).select_from(MemberFeeModel).where(*conditions)
        )
        rows = self.session.execute(
            self._select()
            .where(*conditions)
            .order_by(MemberFeeModel.due_date, MemberFeeModel.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return FeePage(tuple(self._to_fee(*row) for row in rows), total or 0, page, page_size)

    def for_member(self, member_id: int) -> Sequence[Fee]:
        rows = self.session.execute(
            self._select()
            .where(MemberFeeModel.member_id == member_id)
            # Pendentes primeiro (vencimento mais próximo), depois as pagas mais recentes.
            .order_by(
                case((MemberFeeModel.status == FeeStatus.PENDING.value, 0), else_=1),
                case(
                    (MemberFeeModel.status == FeeStatus.PENDING.value, MemberFeeModel.due_date),
                    else_=None,
                ),
                MemberFeeModel.paid_at.desc(),
                MemberFeeModel.id,
            )
        )
        return [self._to_fee(*row) for row in rows]

    def update(self, fee_id: int, data: UpdateFeeData) -> Fee:
        values = {
            key: value
            for key, value in {
                "description": data.description,
                "amount": data.amount,
                "due_date": data.due_date,
            }.items()
            if value is not None
        }
        self.session.execute(
            update(MemberFeeModel)
            .where(MemberFeeModel.id == fee_id)
            .values(**values, updated_at=func.now())
        )
        fee = self.get(fee_id)
        self.session.commit()
        assert fee is not None
        return fee

    def pay(self, fee_id: int, data: PaymentData) -> Fee:
        self.session.execute(
            update(MemberFeeModel)
            .where(MemberFeeModel.id == fee_id)
            .values(
                status=FeeStatus.PAID.value,
                paid_at=data.paid_at,
                payment_method=data.method.value,
                paid_via=data.paid_via.value,
                updated_at=func.now(),
            )
        )
        fee = self.get(fee_id)
        self.session.commit()
        assert fee is not None
        return fee

    def delete(self, fee_id: int) -> None:
        self.session.execute(delete(MemberFeeModel).where(MemberFeeModel.id == fee_id))
        self.session.commit()

    def pending_members(self, today: date) -> Sequence[PendingMember]:
        pending = MemberFeeModel.status == FeeStatus.PENDING.value
        overdue = func.count().filter(MemberFeeModel.due_date < today)
        rows = self.session.execute(
            select(
                MemberModel.id,
                MemberModel.name,
                MemberModel.email,
                func.count().label("pending_count"),
                func.sum(MemberFeeModel.amount).label("pending_total"),
                overdue.label("overdue_count"),
                func.min(MemberFeeModel.due_date).label("oldest_due_date"),
            )
            .join(MemberModel, MemberModel.id == MemberFeeModel.member_id)
            .where(pending)
            .group_by(MemberModel.id)
            # Quem está há mais tempo devendo aparece primeiro.
            .order_by(func.min(MemberFeeModel.due_date), MemberModel.name, MemberModel.id)
        )
        return [
            PendingMember(
                member=FeeMember(row.id, row.name, row.email),
                pending_count=row.pending_count,
                pending_total=row.pending_total,
                overdue_count=row.overdue_count,
                oldest_due_date=row.oldest_due_date,
            )
            for row in rows
        ]
