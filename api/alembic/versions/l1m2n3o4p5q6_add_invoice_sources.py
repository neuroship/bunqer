"""Add invoice sources, fetch runs, provider settings

Revision ID: l1m2n3o4p5q6
Revises: k1l2m3n4o5p6
Create Date: 2026-09-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'l1m2n3o4p5q6'
down_revision: Union[str, None] = 'k1l2m3n4o5p6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'provider_settings',
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('value', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('key'),
    )
    op.create_table(
        'invoice_sources',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('login_url', sa.String(length=1000), nullable=True),
        sa.Column('op_item_ref', sa.String(length=500), nullable=True),
        sa.Column('instructions', sa.Text(), nullable=True),
        sa.Column('gmail_query', sa.String(length=1000), nullable=True),
        sa.Column('gmail_email', sa.String(length=255), nullable=True),
        sa.Column('gmail_token', sa.Text(), nullable=True),
        sa.Column('last_run_at', sa.DateTime(), nullable=True),
        sa.Column('last_status', sa.String(length=20), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'invoice_fetch_runs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('source_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('started_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('documents_found', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('documents_new', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('documents_matched', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('log', sa.Text(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('browserbase_session_id', sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(['source_id'], ['invoice_sources.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_invoice_fetch_runs_source_id', 'invoice_fetch_runs', ['source_id'])
    op.add_column('documents', sa.Column('source_id', sa.Integer(), nullable=True))
    op.add_column('documents', sa.Column('origin_ref', sa.String(length=500), nullable=True))
    op.create_foreign_key(
        'fk_documents_source_id', 'documents', 'invoice_sources', ['source_id'], ['id'], ondelete='SET NULL'
    )
    op.create_index('ix_documents_origin_ref', 'documents', ['origin_ref'])


def downgrade() -> None:
    op.drop_index('ix_documents_origin_ref', table_name='documents')
    op.drop_constraint('fk_documents_source_id', 'documents', type_='foreignkey')
    op.drop_column('documents', 'origin_ref')
    op.drop_column('documents', 'source_id')
    op.drop_index('ix_invoice_fetch_runs_source_id', table_name='invoice_fetch_runs')
    op.drop_table('invoice_fetch_runs')
    op.drop_table('invoice_sources')
    op.drop_table('provider_settings')
