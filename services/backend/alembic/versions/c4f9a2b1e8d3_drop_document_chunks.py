"""drop local document_chunks; RAG lives in Cloudflare AI Search

Revision ID: c4f9a2b1e8d3
Revises: 7d1c4e8a9f20
"""

from typing import Sequence, Union

from alembic import op


revision: str = "c4f9a2b1e8d3"
down_revision: Union[str, Sequence[str], None] = "7d1c4e8a9f20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS document_chunks")


def downgrade() -> None:
    # Vectors are owned by Cloudflare AI Search now; restoring the local table
    # would not recover embeddings. Re-upload documents after a downgrade.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS document_chunks (
            id UUID PRIMARY KEY,
            document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            professor_collection VARCHAR(100) NOT NULL,
            chunk_index INTEGER NOT NULL DEFAULT 0,
            text TEXT NOT NULL,
            embedding BYTEA,
            page_label VARCHAR(100),
            metadata JSON,
            created_at TIMESTAMP WITHOUT TIME ZONE
        )
        """
    )
