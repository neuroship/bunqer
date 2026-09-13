"""Add optional 1Password TOTP reference to invoice sources

Revision ID: n1o2p3q4r5s6
Revises: m1n2o3p4q5r6
Create Date: 2026-09-13 23:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'n1o2p3q4r5s6'
down_revision: Union[str, None] = 'm1n2o3p4q5r6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('invoice_sources', sa.Column('op_totp_ref', sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column('invoice_sources', 'op_totp_ref')
