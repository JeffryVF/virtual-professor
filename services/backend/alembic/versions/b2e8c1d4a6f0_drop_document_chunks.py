"""drop leftover pgvector document_chunks; vectors now live in Qdrant Cloud

Revision ID: b2e8c1d4a6f0
Revises: 7d1c4e8a9f20
"""

from typing import Sequence, Union

from alembic import op


revision: str = "b2e8c1d4a6f0"
down_revision: Union[str, Sequence[str], None] = "7d1c4e8a9f20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS document_chunks")


def downgrade() -> None:
    # Embeddings are stored in Qdrant Cloud; do not recreate a pgvector table.
    pass
