"""default route anunciado, política importada e produto do upstream

Revision ID: a3d1c7e5b9f2
Revises: f2b7d4a91c3e
Create Date: 2026-09-16
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a3d1c7e5b9f2'
down_revision: str | Sequence[str] | None = 'f2b7d4a91c3e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# §3.2: a cópia preserva a intenção de quem marcou "Default Route" — o efeito
# errado era o do render, e o anúncio só chega ao equipamento numa CR. As
# sessões de upstream ficam intactas: nelas o campo sempre significou aceitar a
# default do provedor. `circuit_id` é NOT NULL e único em `upstream_circuits`,
# então o `NOT IN` não tem o caso do NULL que engoliria a lista inteira.
_CAMINHO_DE_CLIENTE = """
UPDATE bgp_sessions
   SET default_route_advertise = allow_default_route,
       allow_default_route = false
 WHERE circuit_id NOT IN (SELECT circuit_id FROM upstream_circuits)
"""

_CAMINHO_DE_VOLTA = """
UPDATE bgp_sessions
   SET allow_default_route = default_route_advertise,
       default_route_advertise = false
 WHERE circuit_id NOT IN (SELECT circuit_id FROM upstream_circuits)
"""


def upgrade() -> None:
    """As colunas da frente e a cópia do default route (§3/§4/§7 do design)."""
    op.add_column(
        "bgp_sessions",
        sa.Column("default_route_advertise", sa.Boolean(),
                  server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "bgp_sessions", sa.Column("import_route_policy", sa.String(length=63), nullable=True)
    )
    op.add_column(
        "bgp_sessions", sa.Column("export_route_policy", sa.String(length=63), nullable=True)
    )
    op.add_column(
        "upstreams", sa.Column("produto_import", sa.String(length=16), nullable=True)
    )
    op.execute(_CAMINHO_DE_CLIENTE)


def downgrade() -> None:
    """A volta perde o que foi marcado em `default_route_advertise` depois da
    migração: é o esperado para uma coluna recém-criada (§3.2)."""
    op.execute(_CAMINHO_DE_VOLTA)
    op.drop_column("upstreams", "produto_import")
    op.drop_column("bgp_sessions", "export_route_policy")
    op.drop_column("bgp_sessions", "import_route_policy")
    op.drop_column("bgp_sessions", "default_route_advertise")
