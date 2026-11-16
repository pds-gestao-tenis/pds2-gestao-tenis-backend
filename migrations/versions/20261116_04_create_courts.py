"""Quadras do clube, gerenciadas por administradores."""

import sqlalchemy as sa
from alembic import op

revision = "20261116_04"
down_revision = "20261015_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "courts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("address", sa.String(255), nullable=False),
        sa.Column("size_m2", sa.Numeric(8, 2), nullable=False),
        sa.Column("max_players", sa.Integer(), nullable=False),
        sa.Column("hourly_price", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("name", name="uq_courts_name"),
        sa.CheckConstraint("size_m2 > 0", name="ck_courts_size_positive"),
        sa.CheckConstraint("max_players BETWEEN 1 AND 50", name="ck_courts_max_players"),
        sa.CheckConstraint("hourly_price >= 0", name="ck_courts_hourly_price"),
    )


def downgrade() -> None:
    op.drop_table("courts")
