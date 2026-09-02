"""device ssh_port

Revision ID: a8acda79738d
Revises: 4b9aa889400e
Create Date: 2026-09-02 13:00:04.588082

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a8acda79738d"
down_revision: str | Sequence[str] | None = "4b9aa889400e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Porta SSH de gerenciamento por device (None = 22 na conexão)."""
    op.add_column("devices", sa.Column("ssh_port", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("devices", "ssh_port")
