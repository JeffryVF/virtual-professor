"""Idempotent seeding of the default admin user from environment variables."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from dependencies.auth import hash_password
from models.user import User

log = logging.getLogger(__name__)


async def seed_default_admin(db: AsyncSession) -> User | None:
    """Create the default admin user when ``ADMIN_EMAIL``/``ADMIN_PASSWORD`` are set.

    Idempotent: if a user with that email already exists (any role), it is left
    untouched. Returns the created user, or ``None`` when no credentials are
    configured or the user already exists.
    """
    if not settings.admin_email or not settings.admin_password:
        log.info("ADMIN_EMAIL/ADMIN_PASSWORD not set — skipping default admin seed")
        return None

    email = settings.admin_email.strip().lower()
    result = await db.execute(select(User).where(User.email == email))
    existing = result.scalar_one_or_none()
    if existing:
        log.info("Default admin already exists (%s) — nothing to do", email)
        return None

    user = User(
        email=email,
        hashed_password=hash_password(settings.admin_password),
        role="admin",
        name=(settings.admin_name or "Administrator").strip(),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    log.info("Seeded default admin user: %s", email)
    return user