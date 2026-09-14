"""VSI multiponto: flow_label/description e vsi_id na CR (Fase 4, parte 3)

Revision ID: 9b1f7c4e2a05
Revises: e48a9c6b2d71
Create Date: 2026-09-13 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '9b1f7c4e2a05'
down_revision: str | Sequence[str] | None = 'e48a9c6b2d71'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Campos do VSI multiponto e o vínculo da CR de escopo vsi."""
    op.add_column(
        "vsi_services",
        sa.Column("flow_label", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("vsi_services", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("change_requests", sa.Column("vsi_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_change_requests_vsi_id", "change_requests", "vsi_services", ["vsi_id"], ["id"],
    )


def downgrade() -> None:
    """Desfaz na ordem inversa da FK (o índice da FK cai junto da constraint)."""
    op.drop_constraint("fk_change_requests_vsi_id", "change_requests", type_="foreignkey")
    op.drop_column("change_requests", "vsi_id")
    op.drop_column("vsi_services", "description")
    op.drop_column("vsi_services", "flow_label")
