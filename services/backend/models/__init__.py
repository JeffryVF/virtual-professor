# Register all models so SQLAlchemy Base.metadata can discover them.
from models.db import Base  # noqa: F401
from models.user import RefreshToken, User  # noqa: F401
