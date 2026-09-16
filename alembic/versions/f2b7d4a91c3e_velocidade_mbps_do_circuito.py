"""velocidade do circuito em Mbps

Revision ID: f2b7d4a91c3e
Revises: c4a8e1f0b7d3
Create Date: 2026-09-15
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f2b7d4a91c3e'
down_revision: str | Sequence[str] | None = 'c4a8e1f0b7d3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """A velocidade contratada, em Mbps (§3 do design).

    Nula em todo circuito que já existe: nula é "não sei a velocidade", e o
    render não emite descrição de velocidade nem QoS enquanto for assim.
    """
    op.add_column("circuits", sa.Column("velocidade_mbps", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("circuits", "velocidade_mbps")
