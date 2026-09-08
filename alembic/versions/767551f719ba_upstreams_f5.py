"""upstreams_f5

Revision ID: 767551f719ba
Revises: b8c714be9ba5
Create Date: 2026-09-08 09:31:06.009851

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


from alembic import op

# revision identifiers, used by Alembic.
revision: str = '767551f719ba'
down_revision: str | Sequence[str] | None = 'b8c714be9ba5'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Fase 5 (upstreams): tabelas novas, enums e seeds de importação ($4.1).

    Valores novos em enums existentes usam ADD VALUE IF NOT EXISTS (padrão
    9081b87de351); enums novos nascem aqui com as tabelas que os usam.
    Reexecutável: ADD VALUE IF NOT EXISTS, CREATE TYPE guardado e seeds
    `on conflict do nothing` (idempotência $3.2).
    """
    op.execute("ALTER TYPE org_kind ADD VALUE IF NOT EXISTS 'operadora'")
    op.execute("ALTER TYPE vlan_mode ADD VALUE IF NOT EXISTS 'none'")
    op.execute("ALTER TYPE auth_origin ADD VALUE IF NOT EXISTS 'irr'")
    op.execute("ALTER TYPE auth_origin ADD VALUE IF NOT EXISTS 'rpki'")
    op.execute("ALTER TYPE change_escopo ADD VALUE IF NOT EXISTS 'upstream'")
    for tipo, valores in (
        ("community_tipo", "'padrao','acao_blackhole','acao_prepend','acao_lp','informacao','tag_produto'"),
        ("upstream_tipo", "'transito','ix','pni','contingencia'"),
        ("upstream_papel", "'principal','contingencia'"),
        ("ucomm_purpose", "'blackhole','prepend','lp','info'"),
        ("ucomm_dir", "'import','export','ambos'"),
    ):
        op.execute(
            f"DO $do$ BEGIN CREATE TYPE {tipo} AS ENUM ({valores}); "
            f"EXCEPTION WHEN duplicate_object THEN NULL; END $do$"
        )

    op.add_column('devices', sa.Column('loopback', sa.String(length=64), nullable=True))
    op.alter_column('circuits', 'access_device_id', existing_type=sa.Integer(), nullable=True)
    op.add_column(
        'communities',
        sa.Column('tipo', postgresql.ENUM('community_tipo', name='community_tipo', create_type=False), nullable=True),
    )
    op.execute("UPDATE communities SET tipo = 'padrao' WHERE tipo IS NULL")
    op.alter_column('communities', 'tipo', nullable=False, server_default=sa.text("'padrao'"))
    op.add_column('bgp_prefix_authorizations', sa.Column('validacao', sa.String(length=32), nullable=True))
    op.add_column('change_requests', sa.Column('upstream_id', sa.Integer(), nullable=True))

    op.create_table('upstreams',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('tipo', postgresql.ENUM('transito', 'ix', 'pni', 'contingencia', name='upstream_tipo', create_type=False), nullable=False),
    sa.Column('capacity', sa.String(length=32), nullable=True),
    sa.Column('priority', sa.Integer(), nullable=True),
    sa.Column('cost', sa.String(length=32), nullable=True),
    sa.Column('organization_id', sa.Integer(), nullable=False),
    sa.Column('expected_prefixes_v4', sa.Integer(), nullable=True),
    sa.Column('expected_prefixes_v6', sa.Integer(), nullable=True),
    sa.Column('max_prefix_margin_pct', sa.Integer(), nullable=False),
    sa.Column('rpki_enabled', sa.Boolean(), nullable=False),
    sa.Column('entrada_local_preference', sa.Integer(), nullable=True),
    sa.Column('contingencia_local_preference', sa.Integer(), nullable=True),
    sa.Column('contingencia_prepend', sa.Integer(), nullable=True),
    sa.Column('contingencia_notes', sa.Text(), nullable=True),
    sa.Column('admin_status', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('upstream_circuits',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('upstream_id', sa.Integer(), nullable=False),
    sa.Column('circuit_id', sa.Integer(), nullable=False),
    sa.Column('papel', postgresql.ENUM('principal', 'contingencia', name='upstream_papel', create_type=False), nullable=False),
    sa.Column('ordem', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['circuit_id'], ['circuits.id'], ),
    sa.ForeignKeyConstraint(['upstream_id'], ['upstreams.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('upstream_id', 'circuit_id')
    )
    op.create_table('upstream_communities',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('upstream_id', sa.Integer(), nullable=False),
    sa.Column('purpose', postgresql.ENUM('blackhole', 'prepend', 'lp', 'info', name='ucomm_purpose', create_type=False), nullable=False),
    sa.Column('value', sa.String(length=64), nullable=False),
    sa.Column('direcao', postgresql.ENUM('import', 'export', 'ambos', name='ucomm_dir', create_type=False), nullable=False),
    sa.Column('regiao', sa.String(length=64), nullable=True),
    sa.Column('bloquear', sa.Boolean(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('admin_status', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['upstream_id'], ['upstreams.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('upstream_id', 'purpose', 'value', 'regiao')
    )
    op.create_table('roas',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('prefix', sa.String(length=64), nullable=False),
    sa.Column('origin_asn', sa.BigInteger(), nullable=False),
    sa.Column('max_length', sa.Integer(), nullable=True),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('valid_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('imported_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('prefix', 'origin_asn', 'max_length')
    )
    op.create_table('irr_cache',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('key', sa.String(length=128), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('queried_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source', 'key')
    )
    op.create_foreign_key('fk_change_requests_upstream', 'change_requests', 'upstreams',
                          ['upstream_id'], ['id'])

    # Seeds de importação de upstream (§4.1) — idempotente (padrão 6973e567cc43).
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "insert into bgp_policy_profiles (name, label, direction, kind, admin_status) "
            "values (:name, :label, 'import', 'produto', true) on conflict do nothing"
        ),
        [{"name": "up-full", "label": "Full (trânsito/IX)"},
         {"name": "up-parcial", "label": "Parcial (comunidade do provedor)"},
         {"name": "up-default", "label": "Somente default"}],
    )


def downgrade() -> None:
    """Reversão: drop das tabelas/colunas/tipos novos; valores adicionados aos
    enums existentes (org_kind, vlan_mode, auth_origin, change_escopo) ficam
    (limite do PG: DROP VALUE indisponível — padrão 9081b87de351)."""
    op.drop_constraint('fk_change_requests_upstream', 'change_requests', type_='foreignkey')
    op.drop_column('change_requests', 'upstream_id')
    op.drop_column('bgp_prefix_authorizations', 'validacao')
    op.drop_column('communities', 'tipo')
    op.drop_column('devices', 'loopback')
    op.alter_column('circuits', 'access_device_id', existing_type=sa.Integer(), nullable=False)
    op.drop_table('irr_cache')
    op.drop_table('roas')
    op.drop_table('upstream_communities')
    op.drop_table('upstream_circuits')
    op.drop_table('upstreams')
    for tipo in ('community_tipo', 'upstream_tipo', 'upstream_papel', 'ucomm_purpose', 'ucomm_dir'):
        op.execute(f"DROP TYPE IF EXISTS {tipo}")
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "delete from bgp_policy_profiles "
            "where name in ('up-full', 'up-parcial', 'up-default') and direction = 'import'"
        )
    )
