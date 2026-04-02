"""add raw_json column to transactions

Revision ID: 2d9ebf21f237
Revises: ccd7574f5b47
Create Date: 2026-02-04 08:16:12.613304

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2d9ebf21f237'
down_revision: Union[str, None] = 'ccd7574f5b47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('transactions', sa.Column('raw_json', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('transactions', 'raw_json')
