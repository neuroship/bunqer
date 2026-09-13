"""Link documents to the fetch run that collected them

Revision ID: p1q2r3s4t5u6
Revises: o1p2q3r4s5t6
Create Date: 2026-09-14 00:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'p1q2r3s4t5u6'
down_revision: Union[str, None] = 'o1p2q3r4s5t6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('documents', sa.Column('run_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_documents_run_id', 'documents', 'invoice_fetch_runs', ['run_id'], ['id'], ondelete='SET NULL'
    )
    op.create_index('ix_documents_run_id', 'documents', ['run_id'])


def downgrade() -> None:
    op.drop_index('ix_documents_run_id', table_name='documents')
    op.drop_constraint('fk_documents_run_id', 'documents', type_='foreignkey')
    op.drop_column('documents', 'run_id')
