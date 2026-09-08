"""upstream_circuits_circuito_unico

BR-1 (§7) no banco: circuito pertence a no máximo um upstream (ruling R-07) —
a unicidade semântica é em circuit_id, não na composta (upstream_id, circuit_id)
que deixava a corrida entre dois vincular_circuito concorrentes passar.

Revision ID: 7dd3d6db4796
Revises: 767551f719ba
Create Date: 2026-09-08 10:13:29.925854

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '7dd3d6db4796'
down_revision: str | Sequence[str] | None = '767551f719ba'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Troca a UNIQUE composta pela unicidade de circuit_id (um upstream por circuito)."""
    op.drop_constraint(
        'upstream_circuits_upstream_id_circuit_id_key', 'upstream_circuits', type_='unique'
    )
    op.create_unique_constraint(
        'uq_upstream_circuits_circuit_id', 'upstream_circuits', ['circuit_id']
    )


def downgrade() -> None:
    """Re-cria a UNIQUE composta (nome autogerado original 767551f719ba)."""
    op.drop_constraint(
        'uq_upstream_circuits_circuit_id', 'upstream_circuits', type_='unique'
    )
    op.create_unique_constraint(
        'upstream_circuits_upstream_id_circuit_id_key',
        'upstream_circuits',
        ['upstream_id', 'circuit_id'],
    )
