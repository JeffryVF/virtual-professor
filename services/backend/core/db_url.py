"""Database URL helpers shared by the app and Alembic."""


def async_database_url(url: str) -> str:
    """Convert a sync SQLAlchemy URL to the asyncpg (or aiosqlite) driver URL.

    Render and Supabase often emit ``postgres://``. SQLAlchemy needs
    ``postgresql://``, and this app's async engine needs ``postgresql+asyncpg://``.
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url
