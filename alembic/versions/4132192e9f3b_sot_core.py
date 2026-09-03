"""sot_core

Revision ID: 4132192e9f3b
Revises: a8acda79738d
Create Date: 2026-09-02 14:48:19.534618

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '4132192e9f3b'
down_revision: str | Sequence[str] | None = 'a8acda79738d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Núcleo da SoT: sites/organizações/contatos/circuitos + VLANs/enlaces p2p.

    devices.site (string, F1) vira devices.site_id → sites homônimos criados
    a partir dos valores existentes (dados preservados, §14.1).
    """
    op.create_table('sites',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('city', sa.String(length=128), nullable=True),
    sa.Column('uf', sa.String(length=2), nullable=True),
    sa.Column('p2p_ipv4_block', sa.String(length=64), nullable=True),
    sa.Column('p2p_ipv6_base', sa.String(length=64), nullable=True),
    sa.Column('admin_status', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('organizations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('legal_name', sa.String(length=255), nullable=True),
    sa.Column('kind', sa.Enum('downstream', 'parceiro', name='org_kind'), nullable=False),
    sa.Column('asn', sa.Integer(), nullable=True),
    sa.Column('irr_as_set', sa.String(length=64), nullable=True),
    sa.Column('commercial_status', sa.String(length=16), nullable=False),
    sa.Column('operational_status', sa.String(length=16), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('admin_status', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('asn'),
    sa.UniqueConstraint('name')
    )
    op.create_table('contacts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('organization_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=True),
    sa.Column('phone', sa.String(length=32), nullable=True),
    sa.Column('kind', sa.Enum('tecnico', 'noc', 'admin', name='contact_kind'), nullable=False),
    sa.Column('admin_status', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('circuits',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('code', sa.String(length=64), nullable=False),
    sa.Column('organization_id', sa.Integer(), nullable=False),
    sa.Column('site_id', sa.Integer(), nullable=False),
    sa.Column('access_device_id', sa.Integer(), nullable=False),
    sa.Column('access_port', sa.String(length=64), nullable=False),
    sa.Column('edge_device_id', sa.Integer(), nullable=False),
    sa.Column('backup_edge_device_id', sa.Integer(), nullable=True),
    sa.Column('stack', sa.Enum('ipv4', 'ipv6', 'dual', name='circuit_stack'), nullable=False),
    sa.Column('vlan_mode', sa.Enum('unica', 'separada', name='vlan_mode'), nullable=False),
    sa.Column('qinq', sa.Boolean(), nullable=False),
    sa.Column('vrf', sa.String(length=64), nullable=True),
    sa.Column('mtu', sa.Integer(), nullable=True),
    sa.Column('bandwidth', sa.String(length=32), nullable=True),
    sa.Column('bfd', sa.Boolean(), nullable=False),
    sa.Column('p2p_v4_len', sa.Integer(), nullable=False),
    sa.Column('description', sa.String(length=255), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('admin_status', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['access_device_id'], ['devices.id'], ),
    sa.ForeignKeyConstraint(['backup_edge_device_id'], ['devices.id'], ),
    sa.ForeignKeyConstraint(['edge_device_id'], ['devices.id'], ),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
    sa.ForeignKeyConstraint(['site_id'], ['sites.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code')
    )
    op.create_table('vlans',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('site_id', sa.Integer(), nullable=False),
    sa.Column('vid', sa.Integer(), nullable=False),
    sa.Column('kind', sa.Enum('vlan', 's_vlan', name='vlan_kind'), nullable=False),
    sa.Column('family', sa.Enum('ipv4', 'ipv6', name='family'), nullable=True),
    sa.Column('circuit_id', sa.Integer(), nullable=True),
    sa.Column('status', sa.Enum('reservada', 'liberada', name='alloc_status'), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['circuit_id'], ['circuits.id'], ),
    sa.ForeignKeyConstraint(['site_id'], ['sites.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('site_id', 'vid')
    )
    op.create_table('ip_prefixes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('network', sa.String(length=64), nullable=False),
    sa.Column('kind', sa.Enum('p2p', name='prefix_kind'), nullable=False),
    sa.Column('site_id', sa.Integer(), nullable=False),
    sa.Column('circuit_id', sa.Integer(), nullable=True),
    sa.Column('status', sa.Enum('reservada', 'liberada', name='alloc_status'), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['circuit_id'], ['circuits.id'], ),
    sa.ForeignKeyConstraint(['site_id'], ['sites.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('site_id', 'network')
    )
    op.add_column('devices', sa.Column('site_id', sa.Integer(), sa.ForeignKey('sites.id'), nullable=True))
    op.add_column('devices', sa.Column('asn', sa.Integer(), nullable=True))

    # Data move: cada valor distinto de devices.site vira um site homônimo.
    bind = op.get_bind()
    nomes = bind.execute(
        sa.text("select distinct site from devices where site is not null and site <> ''")
    ).scalars()
    for nome in nomes:
        bind.execute(
            sa.text(
                "insert into sites (name, admin_status) values (:nome, true) on conflict do nothing"
            ),
            {'nome': nome},
        )
    bind.execute(
        sa.text(
            "update devices d set site_id = s.id "
            "from sites s where s.name = d.site and d.site is not null and d.site <> ''"
        )
    )
    op.drop_column('devices', 'site')


def downgrade() -> None:
    """Restaura a coluna site (string) com o nome do site de cada device."""
    op.add_column('devices', sa.Column('site', sa.String(length=64), nullable=True))
    bind = op.get_bind()
    bind.execute(
        sa.text("update devices d set site = s.name from sites s where s.id = d.site_id")
    )
    op.drop_column('devices', 'site_id')
    op.drop_column('devices', 'asn')
    op.drop_table('ip_prefixes')
    op.drop_table('vlans')
    op.drop_table('circuits')
    op.drop_table('contacts')
    op.drop_table('organizations')
    op.drop_table('sites')
    # Os tipos ENUM criados pelo upgrade ficam órfãos após o drop das tabelas;
    # sem removê-los, o upgrade seguinte falha com "type ... already exists".
    for tipo in (
        'prefix_kind',
        'alloc_status',
        'family',
        'vlan_kind',
        'vlan_mode',
        'circuit_stack',
        'contact_kind',
        'org_kind',
    ):
        bind.execute(sa.text(f'drop type if exists {tipo}'))
