"""change requests: escopo + l2vc_id (circuit_id nullable) — fase 4 T7

Revision ID: b8c714be9ba5
Revises: 9081b87de351
Create Date: 2026-09-07 13:45:38.210333

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b8c714be9ba5'
down_revision: str | None = '9081b87de351'
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    change_escopo = sa.Enum("circuito", "l2vc", "vsi", name="change_escopo")
    change_escopo.create(op.get_bind(), checkfirst=True)
    op.add_column("change_requests", sa.Column("escopo", change_escopo, server_default="circuito", nullable=False))
    op.add_column("change_requests", sa.Column("l2vc_id", sa.Integer(), nullable=True))
    op.alter_column("change_requests", "circuit_id", existing_type=sa.Integer(), nullable=True)
    op.create_foreign_key("fk_change_requests_l2vc_id", "change_requests", "l2vc_services", ["l2vc_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_change_requests_l2vc_id", "change_requests", type_="foreignkey")
    op.drop_column("change_requests", "l2vc_id")
    op.drop_column("change_requests", "escopo")
    op.alter_column("change_requests", "circuit_id", existing_type=sa.Integer(), nullable=False)
