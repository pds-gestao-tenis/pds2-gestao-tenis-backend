"""US28: bloqueios de horário por manutenção ou por evento do clube."""

import sqlalchemy as sa
from alembic import op

revision = "20261123_10"
down_revision = "20261123_09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "court_maintenance",
        sa.Column("kind", sa.String(12), nullable=False, server_default="maintenance"),
    )
    op.create_check_constraint(
        "ck_court_maintenance_kind", "court_maintenance", "kind IN ('maintenance', 'event')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_court_maintenance_kind", "court_maintenance", type_="check")
    op.drop_column("court_maintenance", "kind")
