"""Add date window to invoice fetch runs

Revision ID: o1p2q3r4s5t6
Revises: n1o2p3q4r5s6
Create Date: 2026-09-14 00:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'o1p2q3r4s5t6'
down_revision: Union[str, None] = 'n1o2p3q4r5s6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('invoice_fetch_runs', sa.Column('date_from', sa.Date(), nullable=True))
    op.add_column('invoice_fetch_runs', sa.Column('date_to', sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column('invoice_fetch_runs', 'date_to')
    op.drop_column('invoice_fetch_runs', 'date_from')
