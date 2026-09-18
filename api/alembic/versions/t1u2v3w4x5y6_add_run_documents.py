"""Add run_documents: every document a fetch run found, new or already known

Revision ID: t1u2v3w4x5y6
Revises: s1t2u3v4w5x6
Create Date: 2026-09-18 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 't1u2v3w4x5y6'
down_revision: Union[str, None] = 's1t2u3v4w5x6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'run_documents',
        sa.Column('run_id', sa.Integer(), sa.ForeignKey('invoice_fetch_runs.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('document_id', sa.Integer(), sa.ForeignKey('documents.id', ondelete='CASCADE'), primary_key=True),
    )
    op.execute(
        "INSERT INTO run_documents (run_id, document_id) "
        "SELECT run_id, id FROM documents WHERE run_id IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_table('run_documents')
