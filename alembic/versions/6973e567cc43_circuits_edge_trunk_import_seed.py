"""circuits_edge_trunk_import_seed

Revision ID: 6973e567cc43
Revises: b1a71e5e129b
Create Date: 2026-09-04 08:04:46.229726

"""
from collections.abc import Sequence

import sqlalchemy as sa


from alembic import op

# revision identifiers, used by Alembic.
revision: str = '6973e567cc43'
down_revision: str | Sequence[str] | None = 'b1a71e5e129b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """circuits.edge_trunk (§25.18) + seed do perfil de importação (spec §3.6)."""
    op.add_column('circuits', sa.Column('edge_trunk', sa.String(length=64), nullable=True))

    # Seed do catálogo de importação: destrava import_profile_id (spec decisão 6).
    # on conflict do nothing torna o upgrade reexecutável (idempotência §3.2).
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "insert into bgp_policy_profiles (name, label, direction, kind, admin_status) "
            "values (:name, :label, 'import', 'produto', true) on conflict do nothing"
        ),
        [{"name": "somente-autorizadas", "label": "Somente rotas autorizadas"}],
    )


def downgrade() -> None:
    """Reversão: remove a coluna e o seed de importação."""
    op.drop_column('circuits', 'edge_trunk')
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "delete from bgp_policy_profiles "
            "where name = 'somente-autorizadas' and direction = 'import'"
        )
    )
