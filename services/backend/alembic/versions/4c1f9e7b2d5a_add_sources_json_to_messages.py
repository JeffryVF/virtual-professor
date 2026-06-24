"""add sources_json to messages

Revision ID: 4c1f9e7b2d5a
Revises: a3b2862700ae
Create Date: 2026-06-17 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4c1f9e7b2d5a'
down_revision: Union[str, Sequence[str], None] = 'a3b2862700ae'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add sources_json column to messages table."""
    op.add_column('messages', sa.Column('sources_json', sa.Text(), nullable=True))


def downgrade() -> None:
    """Remove sources_json column from messages table."""
    op.drop_column('messages', 'sources_json')
