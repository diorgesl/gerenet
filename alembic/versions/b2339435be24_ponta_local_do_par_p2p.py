"""ponta local do par p2p

Revision ID: b2339435be24
Revises: 9b1f7c4e2a05
Create Date: 2026-09-14 10:30:21.685453

"""
from collections.abc import Sequence

import sqlalchemy as sa


from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b2339435be24'
down_revision: str | Sequence[str] | None = '9b1f7c4e2a05'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Orientação da ponta do par p2p (spec §7): default preserva o
    comportamento do alocador, que sempre escolhe o par com o local embaixo."""
    # O add_column não cria o tipo (o autogenerate não vê isso): cria antes,
    # como na migration do change_escopo. `checkfirst` porque a descida não
    # remove o tipo.
    ponta_local = sa.Enum("inferior", "superior", name="ponta_local")
    ponta_local.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "ip_prefixes",
        sa.Column("ponta_local", ponta_local, nullable=False, server_default="inferior"),
    )


def downgrade() -> None:
    op.drop_column("ip_prefixes", "ponta_local")
