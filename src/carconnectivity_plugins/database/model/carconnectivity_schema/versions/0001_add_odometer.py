"""Add standalone odometer measurements."""
from alembic import op
import sqlalchemy as sa


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the odometer measurements table when it is not already present."""
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("odometer"):
        op.create_table(
            "odometer",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("vin", sa.String(), nullable=False),
            sa.Column("first_date", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("odometer", sa.Float(), nullable=True),
            sa.ForeignKeyConstraint(["vin"], ["vehicles.vin"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("vin", "first_date", name="odometer_vin_first_date"),
        )


def downgrade() -> None:
    """Drop the odometer measurements table."""
    if sa.inspect(op.get_bind()).has_table("odometer"):
        op.drop_table("odometer")