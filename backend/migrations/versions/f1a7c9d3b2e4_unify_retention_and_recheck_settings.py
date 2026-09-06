"""unify backfill/update retention into upload_retention_days, merge live recheck intervals

Revision ID: f1a7c9d3b2e4
Revises: c2a419e7b8f3
Create Date: 2026-09-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a7c9d3b2e4'
down_revision: Union[str, None] = 'c2a419e7b8f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('app_settings', sa.Column('upload_retention_days', sa.Integer(), nullable=True))
    op.add_column('app_settings', sa.Column('live_recheck_interval_minutes', sa.Integer(), nullable=True))
    # Carry forward the larger of the two prior retention windows (backfill
    # was the deeper of the two) rather than silently shrinking anyone's
    # effective history depth by defaulting to the smaller update_lookback_days.
    op.execute(
        "UPDATE app_settings SET upload_retention_days = "
        "CASE WHEN backfill_days >= update_lookback_days THEN backfill_days ELSE update_lookback_days END"
    )
    op.execute("UPDATE app_settings SET live_recheck_interval_minutes = 5")
    with op.batch_alter_table('app_settings') as batch_op:
        batch_op.alter_column('upload_retention_days', nullable=False)
        batch_op.alter_column('live_recheck_interval_minutes', nullable=False)
        batch_op.drop_column('backfill_days')
        batch_op.drop_column('backfill_min_count')
        batch_op.drop_column('update_lookback_days')

    with op.batch_alter_table('backfill_tasks') as batch_op:
        batch_op.drop_column('target_min_count')


def downgrade() -> None:
    op.add_column('backfill_tasks', sa.Column('target_min_count', sa.Integer(), nullable=True))
    op.execute("UPDATE backfill_tasks SET target_min_count = 50")
    with op.batch_alter_table('backfill_tasks') as batch_op:
        batch_op.alter_column('target_min_count', nullable=False)

    op.add_column('app_settings', sa.Column('backfill_days', sa.Integer(), nullable=True))
    op.add_column('app_settings', sa.Column('backfill_min_count', sa.Integer(), nullable=True))
    op.add_column('app_settings', sa.Column('update_lookback_days', sa.Integer(), nullable=True))
    op.execute("UPDATE app_settings SET backfill_days = upload_retention_days")
    op.execute("UPDATE app_settings SET backfill_min_count = 50")
    op.execute("UPDATE app_settings SET update_lookback_days = upload_retention_days")
    with op.batch_alter_table('app_settings') as batch_op:
        batch_op.alter_column('backfill_days', nullable=False)
        batch_op.alter_column('backfill_min_count', nullable=False)
        batch_op.alter_column('update_lookback_days', nullable=False)
        batch_op.drop_column('upload_retention_days')
        batch_op.drop_column('live_recheck_interval_minutes')
