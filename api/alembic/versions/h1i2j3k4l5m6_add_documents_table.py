"""Add documents table

Revision ID: h1i2j3k4l5m6
Revises: g1h2i3j4k5l6
Create Date: 2026-04-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'h1i2j3k4l5m6'
down_revision: Union[str, None] = 'g1h2i3j4k5l6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'documents',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('filename', sa.String(length=500), nullable=False),
        sa.Column('s3_key', sa.String(length=1000), nullable=False),
        sa.Column('content_type', sa.String(length=100), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('doc_type', sa.String(length=30), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('ocr_text', sa.Text(), nullable=True),
        sa.Column('extracted_data', sa.Text(), nullable=True),
        sa.Column('vendor_name', sa.String(length=500), nullable=True),
        sa.Column('invoice_number', sa.String(length=100), nullable=True),
        sa.Column('invoice_date', sa.Date(), nullable=True),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('total_amount', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('tax_subject', sa.String(length=500), nullable=True),
        sa.Column('payment_reference', sa.String(length=200), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('s3_key'),
    )


def downgrade() -> None:
    op.drop_table('documents')
