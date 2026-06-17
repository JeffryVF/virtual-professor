#!/usr/bin/env python3
"""seed-admin.py — Create the first admin user in the Virtual Professor database.

Usage:
    export DATABASE_URL="postgresql://user:password@host:5432/dbname"
    python scripts/seed-admin.py --email admin@example.com --password s3cret! --name "Admin User"

Options:
    --email     Admin user email address (required)
    --password  Admin user password (required, min 8 chars)
    --name      Admin user display name (required)

The script connects to the database, checks if the user already exists,
and creates an admin account if none exists with that email.
"""

import argparse
import asyncio
import os
import sys

# Ensure we can import from the backend package
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
BACKEND_DIR = os.path.join(PROJECT_ROOT, "services", "backend")

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

os.environ.setdefault("DEBUG", "false")


async def seed_admin(email: str, password: str, name: str) -> None:
    """Create an admin user if one doesn't already exist."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL environment variable is not set.", file=sys.stderr)
        print("  export DATABASE_URL=postgresql://user:pass@host:5432/dbname", file=sys.stderr)
        sys.exit(1)

    # Validate password length
    if len(password) < 8:
        print("ERROR: Password must be at least 8 characters.", file=sys.stderr)
        sys.exit(1)
    if len(password) > 128:
        print("ERROR: Password must not exceed 128 characters.", file=sys.stderr)
        sys.exit(1)

    # ── Set up database connection ──────────────────────────────────────────
    # Use the same pattern as core/database.py
    async_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy import select, text

    engine = create_async_engine(async_url, echo=False)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with SessionLocal() as session:
        # ── Check connection ────────────────────────────────────────────────
        try:
            result = await session.execute(text("SELECT 1"))
            result.scalar()
        except Exception as exc:
            print(f"ERROR: Cannot connect to database: {exc}", file=sys.stderr)
            print(f"  URL: {database_url}", file=sys.stderr)
            await engine.dispose()
            sys.exit(1)

        # ── Create tables if they don't exist ───────────────────────────────
        from core.database import Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print("  ✓ Database tables ensured.")

        # ── Check if user exists ────────────────────────────────────────────
        from models.user import User

        result = await session.execute(select(User).where(User.email == email))
        existing_user = result.scalar_one_or_none()

        if existing_user is not None:
            if existing_user.role == "admin":
                print(f"  ✓ Admin user already exists: {email} (role={existing_user.role})")
                await engine.dispose()
                return
            else:
                print(f"  ✓ User '{email}' exists with role='{existing_user.role}'. Upgrading to admin...")
                existing_user.role = "admin"
                await session.commit()
                print(f"  ✓ User '{email}' upgraded to admin.")
                await engine.dispose()
                return

        # ── Create admin user ───────────────────────────────────────────────
        # Use the same bcrypt hash function as dependencies/auth.py
        import bcrypt as _bcrypt

        hashed_pw = _bcrypt.hashpw(password.encode("utf-8"), _bcrypt.gensalt()).decode("utf-8")

        admin_user = User(
            email=email,
            hashed_password=hashed_pw,
            role="admin",
            name=name,
            is_active=True,
        )
        session.add(admin_user)
        await session.commit()
        await session.refresh(admin_user)

        print(f"  ✓ Admin user created: {email}")
        print(f"    ID:   {admin_user.id}")
        print(f"    Name: {admin_user.name}")
        print(f"    Role: {admin_user.role}")

    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create the first admin user for Virtual Professor.",
    )
    parser.add_argument(
        "--email",
        required=True,
        help="Admin user email address",
    )
    parser.add_argument(
        "--password",
        required=True,
        help="Admin user password (min 8 characters)",
    )
    parser.add_argument(
        "--name",
        required=True,
        help="Admin user display name",
    )
    args = parser.parse_args()

    print("═══ Virtual Professor — Seed Admin ═══")
    print(f"  Email:    {args.email}")
    print(f"  Name:     {args.name}")
    print()

    asyncio.run(seed_admin(args.email, args.password, args.name))
    print()
    print("Done.")


if __name__ == "__main__":
    main()
