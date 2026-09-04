"""users and user_sessions

Revision ID: 915d234f47ca
Revises: b1a71e5e129b
Create Date: 2026-09-04

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

USER_ROLES = ("visualizador", "operador", "aprovador", "executor", "administrador")

revision: str = '915d234f47ca'
down_revision: str | Sequence[str] | None = 'b1a71e5e129b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Usuários do gerenet (§17) + sessões web (cookie opaco, hash no banco).

    Sem seed: o primeiro admin nasce via CLI (`gerenet users create`.
    """
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.Enum(*USER_ROLES, name="user_role"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_user_sessions_token_hash"),
    )


def downgrade() -> None:
    op.drop_table("user_sessions")
    op.drop_table("users")
    # O tipo ENUM `user_role` criado pelo upgrade fica órfão após o drop das
    # tabelas; sem removê-lo, o próximo upgrade falha com "type ... already
    # exists" (padrão da sot_core/bgp_sot).
    bind = op.get_bind()
    bind.execute(sa.text("drop type if exists user_role"))
