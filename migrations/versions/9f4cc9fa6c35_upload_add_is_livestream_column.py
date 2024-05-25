"""'Upload': add 'is_livestream' column

Revision ID: 9f4cc9fa6c35
Revises: 7317681455ef
Create Date: 2024-05-22 20:51:08.085059

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9f4cc9fa6c35'
down_revision = '7317681455ef'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('upload', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_livestream', sa.Boolean(), nullable=True))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('upload', schema=None) as batch_op:
        batch_op.drop_column('is_livestream')

    # ### end Alembic commands ###