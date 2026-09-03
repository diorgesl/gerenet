"""bgp_sot

Revision ID: b1a71e5e129b
Revises: d8458305ab7e
Create Date: 2026-09-02 17:18:35.548462

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b1a71e5e129b'
down_revision: str | Sequence[str] | None = 'd8458305ab7e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Sessões BGP, autorizações de prefixo e catálogos seedados (§6.3/§6.4/§25.5-6).

    `bgp_sessions.afi` e `bgp_prefix_authorizations.family` reusam o tipo ENUM
    `family` criado na sot_core (vlans.family) — sem CREATE TYPE novo.
    Os enums `direction`, `profile_kind` e `auth_origin` nascem aqui com as
    tabelas que os usam. `asn_remote` é NOT NULL (garantia do banco, §4);
    `asn_local` fica nullable — o serviço resolve ambos na criação.
    """
    op.create_table('bgp_policy_profiles',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('label', sa.String(length=64), nullable=False),
    sa.Column('direction', sa.Enum('import', 'export', name='direction'), nullable=False),
    sa.Column('kind', sa.Enum('produto', name='profile_kind'), nullable=False),
    sa.Column('prefixes', sa.JSON(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('admin_status', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('communities',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('admin_status', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('bgp_sessions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('circuit_id', sa.Integer(), nullable=False),
    sa.Column('device_id', sa.Integer(), nullable=False),
    sa.Column('afi', postgresql.ENUM('ipv4', 'ipv6', name='family', create_type=False), nullable=False),
    sa.Column('local_address', sa.String(length=64), nullable=False),
    sa.Column('remote_address', sa.String(length=64), nullable=False),
    sa.Column('source_address', sa.String(length=64), nullable=True),
    sa.Column('asn_local', sa.BigInteger(), nullable=True),
    sa.Column('asn_remote', sa.BigInteger(), nullable=False),
    sa.Column('description', sa.String(length=255), nullable=True),
    sa.Column('import_profile_id', sa.Integer(), nullable=True),
    sa.Column('export_profile_id', sa.Integer(), nullable=True),
    sa.Column('maximum_prefix', sa.Integer(), nullable=True),
    sa.Column('maximum_prefix_threshold', sa.Integer(), nullable=True),
    sa.Column('local_preference', sa.Integer(), nullable=True),
    sa.Column('med', sa.Integer(), nullable=True),
    sa.Column('prepend', sa.Integer(), nullable=True),
    sa.Column('keepalive', sa.Integer(), nullable=True),
    sa.Column('holdtime', sa.Integer(), nullable=True),
    sa.Column('bfd_enabled', sa.Boolean(), nullable=False),
    sa.Column('graceful_restart', sa.Boolean(), nullable=False),
    sa.Column('shutdown', sa.Boolean(), nullable=False),
    sa.Column('allow_default_route', sa.Boolean(), nullable=False),
    sa.Column('password_ref', sa.String(length=255), nullable=True),
    sa.Column('admin_status', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['circuit_id'], ['circuits.id'], ),
    sa.ForeignKeyConstraint(['device_id'], ['devices.id'], ),
    sa.ForeignKeyConstraint(['export_profile_id'], ['bgp_policy_profiles.id'], ),
    sa.ForeignKeyConstraint(['import_profile_id'], ['bgp_policy_profiles.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('bgp_session_communities',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('session_id', sa.Integer(), nullable=False),
    sa.Column('community_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['community_id'], ['communities.id'], ),
    sa.ForeignKeyConstraint(['session_id'], ['bgp_sessions.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('session_id', 'community_id')
    )
    op.create_table('bgp_prefix_authorizations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('organization_id', sa.Integer(), nullable=False),
    sa.Column('family', postgresql.ENUM('ipv4', 'ipv6', name='family', create_type=False), nullable=False),
    sa.Column('prefix', sa.String(length=64), nullable=False),
    sa.Column('origin', sa.Enum('manual', name='auth_origin'), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('admin_status', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    # Seeds dos catálogos (§25.5/§25.6): 6 produtos de exportação + 3 communities.
    # on conflict do nothing torna o upgrade reexecutável (idempotência §3.2).
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "insert into bgp_policy_profiles (name, label, direction, kind, admin_status) "
            "values (:name, :label, 'export', 'produto', true) on conflict do nothing"
        ),
        [
            {"name": "default", "label": "Somente default"},
            {"name": "default_internas", "label": "Default + internas"},
            {"name": "parcial", "label": "Tabela parcial"},
            {"name": "full", "label": "Full routing"},
            {"name": "cdn", "label": "CDN"},
            {"name": "personalizado", "label": "Personalizado"},
        ],
    )
    bind.execute(
        sa.text(
            "insert into communities (name, admin_status) values (:name, true) "
            "on conflict do nothing"
        ),
        [{"name": nome} for nome in ("blackhole", "no-export", "no-advertise")],
    )


def downgrade() -> None:
    """Reversão: drop das tabelas BGP; `family` (P1) permanece."""
    op.drop_table('bgp_prefix_authorizations')
    op.drop_table('bgp_session_communities')
    op.drop_table('bgp_sessions')
    op.drop_table('communities')
    op.drop_table('bgp_policy_profiles')
    # Os tipos ENUM criados pelo upgrade ficam órfãos após o drop das tabelas;
    # sem removê-los, o upgrade seguinte falha com "type ... already exists"
    # (padrão da sot_core). `family` fica de fora: é da migração anterior e
    # segue em uso por vlans.family.
    bind = op.get_bind()
    for tipo in ('direction', 'profile_kind', 'auth_origin'):
        bind.execute(sa.text(f'drop type if exists {tipo}'))
