"""liberar recursos do circuito (índices únicos parciais por status reservada)

Revision ID: e48a9c6b2d71
Revises: c7d76824c9ec
Create Date: 2026-09-09 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e48a9c6b2d71'
down_revision: str | Sequence[str] | None = 'c7d76824c9ec'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Liberação (§14.1: linhas ficam, só mudam de status): a exclusividade
    vale só para linhas reservadas — linha liberada pode ter o mesmo VID/par
    reservado de novo por outro circuito ou re-reserva do mesmo."""
    op.drop_index("uq_vlans_site_vid", table_name="vlans")
    op.create_index(
        "uq_vlans_site_vid",
        "vlans",
        ["site_id", "vid"],
        unique=True,
        postgresql_where=sa.text("device_id IS NULL AND status = 'reservada'"),
    )
    op.drop_constraint("ip_prefixes_site_id_network_key", "ip_prefixes", type_="unique")
    op.create_index(
        "uq_ip_prefixes_site_network",
        "ip_prefixes",
        ["site_id", "network"],
        unique=True,
        postgresql_where=sa.text("status = 'reservada'"),
    )


def downgrade() -> None:
    op.drop_index("uq_ip_prefixes_site_network", table_name="ip_prefixes")
    op.create_unique_constraint("ip_prefixes_site_id_network_key", "ip_prefixes", ["site_id", "network"])
    op.drop_index("uq_vlans_site_vid", table_name="vlans")
    op.create_index(
        "uq_vlans_site_vid",
        "vlans",
        ["site_id", "vid"],
        unique=True,
        postgresql_where=sa.text("device_id IS NULL"),
    )
