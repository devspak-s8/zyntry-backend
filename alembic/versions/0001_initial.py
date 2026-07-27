"""Initial migration for Zyntra backend."""

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.core.database import Base
    from alembic import op

    conn = op.get_bind()
    Base.metadata.create_all(bind=conn)


def downgrade() -> None:
    from app.core.database import Base
    from alembic import op

    conn = op.get_bind()
    Base.metadata.drop_all(bind=conn)
