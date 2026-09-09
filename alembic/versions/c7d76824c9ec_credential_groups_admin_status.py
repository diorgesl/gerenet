"""credential_groups admin_status

Revision ID: c7d76824c9ec
Revises: 7dd3d6db4796
Create Date: 2026-09-09 08:51:49.025986

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c7d76824c9ec'
down_revision: str | Sequence[str] | None = '7dd3d6db4796'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """admin_status (desativação §14.1) e updated_at em credential_groups."""
    op.add_column(
        "credential_groups",
        sa.Column("admin_status", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "credential_groups",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("credential_groups", "updated_at")
    op.drop_column("credential_groups", "admin_status")
