"""Add invoices.paid_transaction_id: the transaction that paid the invoice

Revision ID: s1t2u3v4w5x6
Revises: r1s2t3u4v5w6
Create Date: 2026-09-14 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 's1t2u3v4w5x6'
down_revision: Union[str, None] = 'r1s2t3u4v5w6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('invoices', sa.Column('paid_transaction_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_invoices_paid_transaction_id',
        'invoices',
        'transactions',
        ['paid_transaction_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_invoices_paid_transaction_id', 'invoices', type_='foreignkey')
    op.drop_column('invoices', 'paid_transaction_id')
