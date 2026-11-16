"""Agenda das quadras: reservas, fila de espera e jogadores de cada partida."""

import sqlalchemy as sa
from alembic import op

revision = "20261116_05"
down_revision = "20261116_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Necessária para combinar igualdade (court_id) e sobreposição de intervalos no mesmo índice.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.create_table(
        "bookings",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "court_id",
            sa.BigInteger(),
            sa.ForeignKey("courts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "status IN ('confirmed', 'waitlisted', 'cancelled')", name="ck_bookings_status"
        ),
        sa.CheckConstraint(
            "ends_at - starts_at IN (interval '60 minutes', interval '90 minutes')",
            name="ck_bookings_duration",
        ),
        sa.CheckConstraint(
            "(status = 'cancelled') = (cancelled_at IS NOT NULL)", name="ck_bookings_cancelled_at"
        ),
    )
    op.execute(
        "ALTER TABLE bookings ADD CONSTRAINT ex_bookings_confirmed_overlap "
        "EXCLUDE USING gist (court_id WITH =, tstzrange(starts_at, ends_at) WITH &&) "
        "WHERE (status = 'confirmed')"
    )
    op.create_index(
        "ix_bookings_court_status_starts_at", "bookings", ["court_id", "status", "starts_at"]
    )
    op.create_index("ix_bookings_user_id", "bookings", ["user_id"])

    op.create_table(
        "booking_players",
        sa.Column(
            "booking_id",
            sa.BigInteger(),
            sa.ForeignKey("bookings.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_index("ix_booking_players_user_id", "booking_players", ["user_id"])


def downgrade() -> None:
    op.drop_table("booking_players")
    op.drop_table("bookings")
