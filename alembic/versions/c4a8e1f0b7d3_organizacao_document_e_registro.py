"""organização: o documento do registro e a origem `registro`

Revision ID: c4a8e1f0b7d3
Revises: 39e3d1479c6a
Create Date: 2026-09-15 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c4a8e1f0b7d3'
down_revision: str | Sequence[str] | None = '39e3d1479c6a'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations", sa.Column("document", sa.String(length=32), nullable=True)
    )
    # Precedente da F5 (767551f719ba). O valor nasce fora dos dois caminhos da
    # revalidação — `revalidar_autorizacoes` filtra `origin.in_(("irr","rpki"))`
    # —, e é exatamente por isso que ele existe: marcar o bloco do registro
    # como `irr` faria a revalidação consultar `-i origin` no RADB, não achar
    # rota nenhuma no caso comum e marcar tudo `diverge` para sempre.
    op.execute("ALTER TYPE auth_origin ADD VALUE IF NOT EXISTS 'registro'")


def downgrade() -> None:
    op.drop_column("organizations", "document")
    # O valor 'registro' permanece no tipo: o Postgres não remove valor de enum,
    # e recriar o tipo com a coluna em uso custaria mais do que a sobra (mesmo
    # downgrade da F5).
