"""US19-US22: taxas dos membros e registro de pagamentos."""

import sqlalchemy as sa
from alembic import op

revision = "20261123_09"
down_revision = "20261123_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "member_fees",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "member_id",
            sa.BigInteger(),
            sa.ForeignKey("members.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("description", sa.String(120), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("payment_method", sa.String(10)),
        sa.Column("paid_via", sa.String(10)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("amount > 0", name="ck_member_fees_amount_positive"),
        sa.CheckConstraint("status IN ('pending', 'paid')", name="ck_member_fees_status"),
        sa.CheckConstraint(
            "payment_method IS NULL OR payment_method IN ('cash', 'pix', 'card', 'transfer')",
            name="ck_member_fees_payment_method",
        ),
        sa.CheckConstraint(
            "paid_via IS NULL OR paid_via IN ('admin', 'online')", name="ck_member_fees_paid_via"
        ),
        # Paga <=> tem data, forma e origem do pagamento.
        sa.CheckConstraint(
            "(status = 'paid') = (paid_at IS NOT NULL AND payment_method IS NOT NULL "
            "AND paid_via IS NOT NULL)",
            name="ck_member_fees_paid_fields",
        ),
    )
    op.create_index("ix_member_fees_member_status", "member_fees", ["member_id", "status"])
    op.create_index("ix_member_fees_status_due_date", "member_fees", ["status", "due_date"])


def downgrade() -> None:
    op.drop_table("member_fees")
