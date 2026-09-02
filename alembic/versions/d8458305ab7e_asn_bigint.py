"""asn_bigint

Revision ID: d8458305ab7e
Revises: 4132192e9f3b
Create Date: 2026-09-02 16:45:16.326839

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8458305ab7e'
down_revision: Union[str, Sequence[str], None] = '4132192e9f3b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """devices.asn e organizations.asn viram BigInteger (§14.1).

    ASNs de 4 bytes (até 4294967295) estouravam o Integer assinado de 32 bits
    (DataError no flush); dados existentes são todos NULL, alter é seguro.
    """
    op.alter_column(
        'devices', 'asn', existing_type=sa.Integer(), type_=sa.BigInteger(), existing_nullable=True
    )
    op.alter_column(
        'organizations', 'asn', existing_type=sa.Integer(), type_=sa.BigInteger(), existing_nullable=True
    )


def downgrade() -> None:
    """Reversão: BigInteger → Integer nas colunas asn."""
    op.alter_column(
        'devices', 'asn', existing_type=sa.BigInteger(), type_=sa.Integer(), existing_nullable=True
    )
    op.alter_column(
        'organizations', 'asn', existing_type=sa.BigInteger(), type_=sa.Integer(), existing_nullable=True
    )
