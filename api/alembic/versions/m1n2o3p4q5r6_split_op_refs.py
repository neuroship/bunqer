"""Split 1Password item ref into username and password field refs

Revision ID: m1n2o3p4q5r6
Revises: l1m2n3o4p5q6
Create Date: 2026-09-13 23:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'm1n2o3p4q5r6'
down_revision: Union[str, None] = 'l1m2n3o4p5q6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('invoice_sources', sa.Column('op_username_ref', sa.String(length=500), nullable=True))
    op.add_column('invoice_sources', sa.Column('op_password_ref', sa.String(length=500), nullable=True))
    # Carry over existing item refs using the default field names
    op.execute(
        "UPDATE invoice_sources SET op_username_ref = op_item_ref || '/username', "
        "op_password_ref = op_item_ref || '/password' WHERE op_item_ref IS NOT NULL"
    )
    op.drop_column('invoice_sources', 'op_item_ref')


def downgrade() -> None:
    op.add_column('invoice_sources', sa.Column('op_item_ref', sa.String(length=500), nullable=True))
    op.execute(
        "UPDATE invoice_sources SET op_item_ref = regexp_replace(op_username_ref, '/[^/]+$', '') "
        "WHERE op_username_ref IS NOT NULL"
    )
    op.drop_column('invoice_sources', 'op_password_ref')
    op.drop_column('invoice_sources', 'op_username_ref')
