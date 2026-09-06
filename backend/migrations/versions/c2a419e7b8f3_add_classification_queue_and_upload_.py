"""add classification queue and upload duration/live-status columns

Revision ID: c2a419e7b8f3
Revises: 9016370664e3
Create Date: 2026-09-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2a419e7b8f3'
down_revision: Union[str, None] = '9016370664e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('uploads', sa.Column('duration_seconds', sa.Integer(), nullable=True))
    op.add_column('uploads', sa.Column('live_status', sa.String(length=16), nullable=True))
    op.add_column('uploads', sa.Column('scheduled_start_at', sa.DateTime(), nullable=True))

    op.create_table(
        'classification_queue',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('upload_id', sa.Integer(), nullable=False),
        sa.Column('published_at', sa.DateTime(), nullable=False),
        sa.Column('next_check_at', sa.DateTime(), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['upload_id'], ['uploads.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('upload_id', name='uq_classification_queue_upload'),
    )
    op.create_index(
        op.f('ix_classification_queue_upload_id'), 'classification_queue', ['upload_id'], unique=False
    )
    op.create_index(
        op.f('ix_classification_queue_published_at'), 'classification_queue', ['published_at'], unique=False
    )
    op.create_index(
        op.f('ix_classification_queue_next_check_at'), 'classification_queue', ['next_check_at'], unique=False
    )
    with op.batch_alter_table('classification_queue') as batch_op:
        batch_op.alter_column('attempts', server_default=None)


def downgrade() -> None:
    op.drop_index(op.f('ix_classification_queue_next_check_at'), table_name='classification_queue')
    op.drop_index(op.f('ix_classification_queue_published_at'), table_name='classification_queue')
    op.drop_index(op.f('ix_classification_queue_upload_id'), table_name='classification_queue')
    op.drop_table('classification_queue')
    with op.batch_alter_table('uploads') as batch_op:
        batch_op.drop_column('scheduled_start_at')
        batch_op.drop_column('live_status')
        batch_op.drop_column('duration_seconds')
