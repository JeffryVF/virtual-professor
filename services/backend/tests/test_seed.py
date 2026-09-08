"""Tests for the default admin user seeding (services.seed)."""

from unittest.mock import patch

import pytest
from sqlalchemy import select

from dependencies.auth import verify_password
from models.user import User
from services.seed import seed_default_admin


@pytest.mark.asyncio
async def test_seed_creates_admin_when_credentials_set(db_session):
    """GIVEN ADMIN_EMAIL/ADMIN_PASSWORD configured
    WHEN seed_default_admin runs
    THEN an active admin User is created with the hashed password.
    """
    with patch(
        "services.seed.settings",
        admin_email="Admin@Example.com",
        admin_password="s3cret",
        admin_name="Head Admin",
    ):
        user = await seed_default_admin(db_session)

    assert user is not None
    assert user.email == "admin@example.com"  # lowercased
    assert user.role == "admin"
    assert user.is_active is True
    assert user.name == "Head Admin"
    assert verify_password("s3cret", user.hashed_password)


@pytest.mark.asyncio
async def test_seed_is_idempotent(db_session):
    """GIVEN a default admin already exists
    WHEN seed_default_admin runs again
    THEN no duplicate row is created and the original is untouched.
    """
    creds = dict(
        admin_email="admin@example.com", admin_password="s3cret", admin_name="Administrator"
    )
    with patch("services.seed.settings", **creds):
        first = await seed_default_admin(db_session)
    with patch("services.seed.settings", **creds):
        second = await seed_default_admin(db_session)

    assert first is not None
    assert second is None  # already existed

    result = await db_session.execute(
        select(User).where(User.email == "admin@example.com")
    )
    rows = result.scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_seed_skips_when_credentials_missing(db_session, student_user):
    """GIVEN ADMIN_EMAIL/ADMIN_PASSWORD are empty
    WHEN seed_default_admin runs
    THEN nothing is created and the function returns None.
    """
    with patch(
        "services.seed.settings",
        admin_email="",
        admin_password="",
        admin_name="Administrator",
    ):
        user = await seed_default_admin(db_session)

    assert user is None
    result = await db_session.execute(select(User))
    assert len(result.scalars().all()) == 1  # only the student_user fixture


@pytest.mark.asyncio
async def test_seed_does_not_touch_existing_role_with_same_email(db_session, student_user):
    """GIVEN a user with the admin email already exists under another role
    WHEN seed_default_admin runs
    THEN the existing user is preserved (not promoted or duplicated).
    """
    with patch(
        "services.seed.settings",
        admin_email="student@test.com",
        admin_password="s3cret",
        admin_name="Administrator",
    ):
        user = await seed_default_admin(db_session)

    assert user is None
    result = await db_session.execute(
        select(User).where(User.email == "student@test.com")
    )
    existing = result.scalar_one()
    assert existing.role == "student"