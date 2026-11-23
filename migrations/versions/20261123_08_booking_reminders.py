"""US18: registra quando o lembrete da reserva foi enviado (no máximo um por horário)."""

import sqlalchemy as sa
from alembic import op

revision = "20261123_08"
down_revision = "20261116_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bookings", sa.Column("reminder_sent_at", sa.DateTime(timezone=True)))
    op.create_index(
        "ix_bookings_reminder_due",
        "bookings",
        ["starts_at"],
        postgresql_where=sa.text("status = 'confirmed' AND reminder_sent_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_bookings_reminder_due", table_name="bookings")
    op.drop_column("bookings", "reminder_sent_at")
