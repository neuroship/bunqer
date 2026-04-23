"""Add content_hash to documents

Revision ID: j1k2l3m4n5o6
Revises: i1j2k3l4m5n6
Create Date: 2026-04-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'j1k2l3m4n5o6'
down_revision: Union[str, None] = 'i1j2k3l4m5n6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('documents', sa.Column('content_hash', sa.String(length=64), nullable=True))
    op.create_index('ix_documents_content_hash', 'documents', ['content_hash'])


def downgrade() -> None:
    op.drop_index('ix_documents_content_hash', table_name='documents')
    op.drop_column('documents', 'content_hash')
