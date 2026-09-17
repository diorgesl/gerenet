"""plano de communities: vocabulário, alvos, portões e regras de import (spec F1 §4)

Revision ID: 01298554f339
Revises: a3d1c7e5b9f2
Create Date: 2026-09-17 12:39:55.916227

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '01298554f339'
down_revision: str | Sequence[str] | None = 'a3d1c7e5b9f2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """O vocabulário das communities e as quatro tabelas do plano (§4).

    Reexecutável: CREATE TYPE guardado pelo DO/EXCEPTION (idioma da migração
    767551f719ba) e colunas/índices novos, que o Alembic não repete sozinho.
    """
    # Tipos novos: o DO/EXCEPTION é o idioma do repositório (migração 767551f719ba).
    for nome, valores in (
        ("community_banda", ("local", "transito", "cliente", "parceiro", "conjunto", "tamanho", "especial", "instrucao")),
        ("community_origem", ("manual", "adotado")),
        ("community_plan_origem", ("manual", "adotado")),
        ("community_target_papel", ("transito", "ix", "pni", "cdn", "parceiro")),
        ("community_gate_papel", ("upstream", "cdn", "parceiro", "ix")),
        ("community_gate_padrao", ("recusar", "permitir")),
        ("community_import_papel", ("cliente", "parceiro", "transito")),
    ):
        op.execute(
            f"DO $do$ BEGIN CREATE TYPE {nome} AS ENUM "
            f"({', '.join(repr(v) for v in valores)}); "
            "EXCEPTION WHEN duplicate_object THEN NULL; END $do$"
        )

    op.add_column("communities", sa.Column("valor_v4", sa.Integer(), nullable=True))
    op.add_column("communities", sa.Column("valor_v6", sa.Integer(), nullable=True))
    op.add_column("communities", sa.Column("codigo", sa.Integer(), nullable=True))
    op.add_column(
        "communities",
        sa.Column("banda", postgresql.ENUM(name="community_banda", create_type=False), nullable=True),
    )
    op.add_column(
        "communities",
        sa.Column(
            "origem", postgresql.ENUM(name="community_origem", create_type=False),
            nullable=False, server_default="manual",
        ),
    )
    op.add_column("communities", sa.Column("origem_snapshot_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_communities_origem_snapshot", "communities", "device_snapshots",
        ["origem_snapshot_id"], ["id"],
    )
    # Nulos não colidem: um vocabulário de classes convive com o de instruções.
    op.create_index(
        "uq_communities_valor_v4", "communities", ["valor_v4"], unique=True,
        postgresql_where=sa.text("valor_v4 IS NOT NULL"),
    )
    op.create_index(
        "uq_communities_valor_v6", "communities", ["valor_v6"], unique=True,
        postgresql_where=sa.text("valor_v6 IS NOT NULL"),
    )
    op.create_index(
        "uq_communities_codigo", "communities", ["codigo"], unique=True,
        postgresql_where=sa.text("codigo IS NOT NULL AND banda = 'instrucao'"),
    )

    op.create_table(
        "community_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asn_principal", sa.Integer(), nullable=False),
        sa.Column("asns_anunciados", sa.JSON(), nullable=True),
        sa.Column(
            "origem", postgresql.ENUM(name="community_plan_origem", create_type=False),
            nullable=False, server_default="manual",
        ),
        sa.Column("origem_snapshot_id", sa.Integer(), sa.ForeignKey("device_snapshots.id"), nullable=True),
        sa.Column("observacoes", sa.Text(), nullable=True),
        sa.Column("admin_status", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    # Uma linha ativa: o plano é um só (§4.2).
    op.create_index(
        "uq_community_plans_ativa", "community_plans", ["admin_status"], unique=True,
        postgresql_where=sa.text("admin_status"),
    )

    op.create_table(
        "community_targets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nome", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "papel", postgresql.ENUM(name="community_target_papel", create_type=False),
            nullable=False, server_default="transito",
        ),
        sa.Column("codigo_v4", sa.Integer(), nullable=True),
        sa.Column("codigo_v6", sa.Integer(), nullable=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("upstream_id", sa.Integer(), sa.ForeignKey("upstreams.id"), nullable=True),
        sa.Column("classe_import_id", sa.Integer(), sa.ForeignKey("communities.id"), nullable=True),
        sa.Column("gate_nome", sa.String(128), nullable=True),
        sa.Column("parametros", sa.JSON(), nullable=True),
        sa.Column(
            "origem", postgresql.ENUM(name="community_plan_origem", create_type=False),
            nullable=False, server_default="manual",
        ),
        sa.Column("origem_snapshot_id", sa.Integer(), sa.ForeignKey("device_snapshots.id"), nullable=True),
        sa.Column("admin_status", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "community_gates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nome", sa.String(128), nullable=False),
        sa.Column(
            "papel", postgresql.ENUM(name="community_gate_papel", create_type=False),
            nullable=False, server_default="upstream",
        ),
        sa.Column("afi", sa.String(8), nullable=False, server_default="ipv4"),
        sa.Column(
            "padrao", postgresql.ENUM(name="community_gate_padrao", create_type=False),
            nullable=False, server_default="recusar",
        ),
        sa.Column("aceitas", sa.JSON(), nullable=True),
        sa.Column("recusadas", sa.JSON(), nullable=True),
        sa.Column(
            "origem", postgresql.ENUM(name="community_plan_origem", create_type=False),
            nullable=False, server_default="manual",
        ),
        sa.Column("origem_snapshot_id", sa.Integer(), sa.ForeignKey("device_snapshots.id"), nullable=True),
        sa.Column("admin_status", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("nome", "papel", "afi", name="uq_community_gates_nome_papel_afi"),
    )

    op.create_table(
        "community_import_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "papel", postgresql.ENUM(name="community_import_papel", create_type=False), nullable=False,
        ),
        sa.Column("afi", sa.String(8), nullable=False, server_default="ipv4"),
        sa.Column("classe_id", sa.Integer(), sa.ForeignKey("communities.id"), nullable=False),
        sa.Column("condicao", sa.JSON(), nullable=True),
        sa.Column("notas", sa.Text(), nullable=True),
        sa.Column(
            "origem", postgresql.ENUM(name="community_plan_origem", create_type=False),
            nullable=False, server_default="manual",
        ),
        sa.Column("origem_snapshot_id", sa.Integer(), sa.ForeignKey("device_snapshots.id"), nullable=True),
        sa.UniqueConstraint("papel", "afi", name="uq_community_import_rules_papel_afi"),
    )


def downgrade() -> None:
    """Desfaz o plano e as colunas do vocabulário, na ordem inversa."""
    op.drop_table("community_import_rules")
    op.drop_table("community_gates")
    op.drop_table("community_targets")
    op.drop_index("uq_community_plans_ativa", table_name="community_plans")
    op.drop_table("community_plans")
    op.drop_index("uq_communities_codigo", table_name="communities")
    op.drop_index("uq_communities_valor_v6", table_name="communities")
    op.drop_index("uq_communities_valor_v4", table_name="communities")
    op.drop_constraint("fk_communities_origem_snapshot", "communities", type_="foreignkey")
    for coluna in ("origem_snapshot_id", "origem", "banda", "codigo", "valor_v6", "valor_v4"):
        op.drop_column("communities", coluna)
    for nome in (
        "community_import_papel", "community_gate_padrao", "community_gate_papel",
        "community_target_papel", "community_plan_origem", "community_origem", "community_banda",
    ):
        op.execute(f"DROP TYPE IF EXISTS {nome}")
