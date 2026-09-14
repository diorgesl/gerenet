"""descoberta: peers ignorados

Revision ID: 39e3d1479c6a
Revises: b2339435be24
Create Date: 2026-09-14 11:08:06.691591

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


from alembic import op

# revision identifiers, used by Alembic.
revision: str = '39e3d1479c6a'
down_revision: str | Sequence[str] | None = 'b2339435be24'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Lista de ignorados (§11). O tipo `family` já existe (bgp_sessions.afi),
    por isso create_type=False.

    Sem `ALTER TYPE` e sem seed: o tipo nasceu na cadeia do BGP e a tabela é
    escrita só pelo operador (serviço `domain/services/discovery.py`).
    """
    op.create_table(
        "discovery_ignored_peers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("vrf", sa.String(length=64), nullable=True),
        sa.Column("afi", postgresql.ENUM("ipv4", "ipv6", name="family", create_type=False),
                  nullable=False),
        sa.Column("remote_address", sa.String(length=64), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=True),
        sa.Column("autor", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    # Dois índices parciais, não uma UNIQUE composta: em NULL o Postgres não
    # colide, então a exclusividade da instância pública (vrf IS NULL) precisa
    # de índice próprio, senão o mesmo peer público entra duas vezes.
    op.create_index("uq_discovery_ignored_vrf", "discovery_ignored_peers",
                    ["device_id", "vrf", "afi", "remote_address"], unique=True,
                    postgresql_where=sa.text("vrf IS NOT NULL"))
    op.create_index("uq_discovery_ignored_publico", "discovery_ignored_peers",
                    ["device_id", "afi", "remote_address"], unique=True,
                    postgresql_where=sa.text("vrf IS NULL"))


def downgrade() -> None:
    op.drop_index("uq_discovery_ignored_publico", table_name="discovery_ignored_peers")
    op.drop_index("uq_discovery_ignored_vrf", table_name="discovery_ignored_peers")
    op.drop_table("discovery_ignored_peers")
