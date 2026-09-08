"""resize document embeddings for local multilingual-e5-small

Revision ID: 7d1c4e8a9f20
Revises: 4c1f9e7b2d5a
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7d1c4e8a9f20"
down_revision: Union[str, Sequence[str], None] = "4c1f9e7b2d5a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Vectors from the previous provider cannot be converted safely. The
    # document records remain, and the admin UI can re-index them.
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.document_chunks') IS NOT NULL THEN
                TRUNCATE TABLE document_chunks;
                ALTER TABLE document_chunks
                    ALTER COLUMN embedding TYPE vector(384);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.document_chunks') IS NOT NULL THEN
                TRUNCATE TABLE document_chunks;
                ALTER TABLE document_chunks
                    ALTER COLUMN embedding TYPE vector(1024);
            END IF;
        END $$;
        """
    )
