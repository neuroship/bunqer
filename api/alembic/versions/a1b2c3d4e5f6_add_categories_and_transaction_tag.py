"""add categories table and transaction tag field

Revision ID: a1b2c3d4e5f6
Revises: d66ad6e7602e
Create Date: 2026-02-04 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'd66ad6e7602e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create categories table
    op.create_table(
        'categories',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('color', sa.String(length=7), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )

    # Add category_id and tag columns to transactions
    op.add_column('transactions', sa.Column('category_id', sa.Integer(), nullable=True))
    op.add_column('transactions', sa.Column('tag', sa.String(length=255), nullable=True))

    # Add foreign key constraint
    op.create_foreign_key(
        'fk_transactions_category_id',
        'transactions',
        'categories',
        ['category_id'],
        ['id']
    )


def downgrade() -> None:
    # Drop foreign key constraint
    op.drop_constraint('fk_transactions_category_id', 'transactions', type_='foreignkey')

    # Drop columns from transactions
    op.drop_column('transactions', 'tag')
    op.drop_column('transactions', 'category_id')

    # Drop categories table
    op.drop_table('categories')
