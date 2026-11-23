"""US23-US24: nível de habilidade e disponibilidade dos jogadores."""

import sqlalchemy as sa
from alembic import op

revision = "20261123_11"
down_revision = "20261123_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("skill_level", sa.String(12)))
    op.create_check_constraint(
        "ck_users_skill_level",
        "users",
        "skill_level IS NULL OR skill_level IN "
        "('beginner', 'intermediate', 'advanced', 'competitive')",
    )
    op.create_table(
        "player_availability",
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("weekday", sa.SmallInteger(), primary_key=True),
        sa.Column("period", sa.String(10), primary_key=True),
        sa.CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_player_availability_weekday"),
        sa.CheckConstraint(
            "period IN ('morning', 'afternoon', 'evening')", name="ck_player_availability_period"
        ),
    )
    op.create_index("ix_player_availability_slot", "player_availability", ["weekday", "period"])


def downgrade() -> None:
    op.drop_table("player_availability")
    op.drop_constraint("ck_users_skill_level", "users", type_="check")
    op.drop_column("users", "skill_level")
