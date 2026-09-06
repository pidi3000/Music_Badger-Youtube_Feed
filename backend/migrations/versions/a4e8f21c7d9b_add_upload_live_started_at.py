"""add upload live_started_at

Revision ID: a4e8f21c7d9b
Revises: f1a7c9d3b2e4
Create Date: 2026-09-06 00:00:01.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4e8f21c7d9b'
down_revision: Union[str, None] = 'f1a7c9d3b2e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('uploads', sa.Column('live_started_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('uploads') as batch_op:
        batch_op.drop_column('live_started_at')
