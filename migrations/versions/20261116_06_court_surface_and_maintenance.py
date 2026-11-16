"""Piso, cobertura e janelas de manutenção das quadras."""

import sqlalchemy as sa
from alembic import op

revision = "20261116_06"
down_revision = "20261116_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # O default só preenche quadras já existentes; novas quadras informam o piso.
    op.add_column(
        "courts", sa.Column("surface", sa.String(10), nullable=False, server_default="hard")
    )
    op.alter_column("courts", "surface", server_default=None)
    op.add_column(
        "courts", sa.Column("covered", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.create_check_constraint(
        "ck_courts_surface", "courts", "surface IN ('clay', 'hard', 'grass', 'synthetic')"
    )
    op.drop_constraint("uq_courts_name", "courts", type_="unique")
    op.create_index("uq_courts_name", "courts", [sa.text("lower(name)")], unique=True)

    op.create_table(
        "court_maintenance",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "court_id",
            sa.BigInteger(),
            sa.ForeignKey("courts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("ends_at > starts_at", name="ck_court_maintenance_period"),
    )
    op.create_index(
        "ix_court_maintenance_court_ends_at", "court_maintenance", ["court_id", "ends_at"]
    )


def downgrade() -> None:
    op.drop_table("court_maintenance")
    op.drop_index("uq_courts_name", table_name="courts")
    op.create_unique_constraint("uq_courts_name", "courts", ["name"])
    op.drop_constraint("ck_courts_surface", "courts", type_="check")
    op.drop_column("courts", "covered")
    op.drop_column("courts", "surface")
