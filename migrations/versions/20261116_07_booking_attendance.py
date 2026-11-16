"""Confirmação de presença dos jogadores de cada reserva."""

import sqlalchemy as sa
from alembic import op

revision = "20261116_07"
down_revision = "20261116_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "booking_players",
        sa.Column("attendance", sa.String(10), nullable=False, server_default="pending"),
    )
    op.create_check_constraint(
        "ck_booking_players_attendance",
        "booking_players",
        "attendance IN ('pending', 'confirmed', 'declined')",
    )
    # Quem reservou já está confirmado na própria partida.
    op.execute(
        "UPDATE booking_players SET attendance = 'confirmed' FROM bookings "
        "WHERE bookings.id = booking_players.booking_id "
        "AND bookings.user_id = booking_players.user_id"
    )


def downgrade() -> None:
    op.drop_constraint("ck_booking_players_attendance", "booking_players", type_="check")
    op.drop_column("booking_players", "attendance")
