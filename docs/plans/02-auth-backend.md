# 2. Backend Authentication System

## Objective

Implement a complete JWT-based authentication system on the FastAPI backend with User model, registration, login, token refresh, role-based access control, and migration of existing admin endpoints from `X-Admin-Key` to real auth.

## Prerequisites

- Phase 1 (baseline audit) complete — tests passing, README accurate
- `pyjwt` and `passlib[bcrypt]` available in Python environment
- Alembic initialized in `services/backend/`

## Detailed Steps

### Step 1: Add User SQLAlchemy model
- **Action:** Create `services/backend/models/user.py` with the User ORM model.
- **Files:** `services/backend/models/user.py`, `services/backend/models/db.py` (optional — decide if User goes in db.py or a new file)
- **Details:**
  - Model name: `User`, table name: `users`
  - Fields:
    - `id`: `UUID(as_uuid=True)`, primary key, default `uuid.uuid4`
    - `email`: `String(255)`, unique, indexed, nullable=False
    - `hashed_password`: `String(255)`, nullable=False
    - `role`: `Enum(UserRole)` with values `admin`, `student`, `professor`
    - `name`: `String(200)`, nullable=False
    - `is_active`: `Boolean`, default `True`
    - `created_at`: `DateTime`, default `datetime.utcnow`
    - `updated_at`: `DateTime`, default `datetime.utcnow`, onupdate `datetime.utcnow`
  - Mixin or base class: use the existing `Base` from `core.database`
  - Relationship to existing models: discuss whether `Student` and `Professor` models should join to `User` or remain separate. Recommend initially keeping them separate and introducing a `user_id` FK on `Student` and `Professor` in a later migration.
  - Create a `UserRole` enum alongside the model (or inside `db.py` alongside the other enums):

    ```python
    class UserRole(enum.Enum):
        admin = "admin"
        student = "student"
        professor = "professor"
    ```

### Step 2: Add authentication dependencies
- **Action:** Create `services/backend/dependencies/auth.py` with FastAPI dependency functions.
- **Files:** `services/backend/dependencies/auth.py` (new), `services/backend/dependencies/__init__.py` (new, can be empty)
- **Details:**
  - `get_current_user`: Extracts `Authorization: Bearer <token>`, decodes JWT, fetches User from DB, raises 401 if invalid/expired/missing.
  - `require_admin`: Wraps `get_current_user`, checks `user.role == UserRole.admin`, raises 403 if not admin.
  - `require_role(role: UserRole)`: Returns a dependency that checks for a specific role. Factory pattern:

    ```python
    def require_role(required_role: UserRole):
        async def _check(current_user: User = Depends(get_current_user)):
            if current_user.role != required_role:
                raise HTTPException(status_code=403, detail="Insufficient permissions")
            return current_user
        return _check
    ```

  - JWT configuration: read `JWT_SECRET_KEY`, `JWT_ALGORITHM` (default `HS256`), `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` (default 30), `JWT_REFRESH_TOKEN_EXPIRE_DAYS` (default 7) from settings.
  - Token creation functions: `create_access_token(data: dict)`, `create_refresh_token(data: dict)`, `decode_token(token: str) -> dict`.
  - Refresh token model: create a `RefreshToken` SQLAlchemy model linked to User, storing the token hash, expiration, and a `is_revoked` flag for rotation detection.
  - Error responses: all auth errors return JSON `{"detail": "message"}` with appropriate HTTP status codes (401 for auth failures, 403 for role failures).

### Step 3: Create auth schemas
- **Action:** Add Pydantic schemas for authentication.
- **Files:** `services/backend/schemas/auth.py` (new directory `services/backend/schemas/__init__.py` + auth.py)
- **Details:**
  - `UserCreate`: `email` (EmailStr), `password` (str, min_length=8), `name` (str), `role` (UserRole, default=student)
  - `UserResponse`: `id`, `email`, `name`, `role`, `is_active`, `created_at` — no password field
  - `LoginRequest`: `email` (EmailStr), `password` (str)
  - `TokenResponse`: `access_token` (str), `refresh_token` (str), `token_type` (str = "bearer"), `user` (UserResponse)
  - `RefreshRequest`: `refresh_token` (str)
  - Add `EmailStr` validation — requires `pydantic[email]` which is already in requirements.txt

### Step 4: Create auth router
- **Action:** Create `services/backend/routers/auth.py` with auth endpoints.
- **Files:** `services/backend/routers/auth.py`
- **Details:**
  - `POST /auth/register`:
    - Accept `UserCreate`, hash password with `pCryptContext(schemes=["bcrypt"])`.
    - Check for duplicate email — return 409 "Email already registered" if exists.
    - Create User, return `UserResponse` with 201 status.
    - Consider: during initial rollout, restrict registration to `student` role only. Admin/professor accounts are created via seed script or admin endpoint.
  - `POST /auth/login`:
    - Accept `LoginRequest`, verify credentials with `pwd_context.verify()`.
    - Return `TokenResponse` with access + refresh tokens.
    - If inactive user, return 403 "Account disabled".
  - `POST /auth/refresh`:
    - Accept `RefreshRequest`, validate refresh token.
    - Check if refresh token is revoked → if revoked, revoke all tokens for that user (reuse detection).
    - Issue new access + refresh tokens, revoke old refresh token (rotation).
  - `GET /auth/me`:
    - Protected endpoint. Returns current user's `UserResponse`.
    - Useful for frontend to validate token on page load.

### Step 5: Create Alembic migration
- **Action:** Generate and verify migration for User and RefreshToken tables.
- **Files:** `alembic/versions/` (auto-generated migration file)
- **Details:**
  - Initialize Alembic if not already done: `cd services/backend && alembic init alembic`
  - Configure `alembic/env.py` to use the async engine and point to `Base.metadata` from `models.db` (and `models.user`).
  - Run: `alembic revision --autogenerate -m "add users and refresh_tokens"`
  - Verify the generated migration creates:
    - `users` table with all columns, unique index on `email`
    - `refresh_tokens` table with `id`, `token_hash`, `user_id` (FK), `expires_at`, `is_revoked`, `created_at`
  - Migration strategy: use `batch` mode for SQLite compatibility in tests, or use separate migration files per DB.

### Step 6: Migrate admin endpoints from X-Admin-Key to JWT
- **Action:** Replace `APIKeyHeader` dependency in admin router with `require_admin`.
- **Files:** `services/backend/routers/admin.py`
- **Details:**
  - Remove: `from fastapi.security import APIKeyHeader` and the `api_key_header = APIKeyHeader(name="X-Admin-Key")` line.
  - Remove: the admin key validation function that checks `api_key_header` against `settings.admin_api_key`.
  - Replace with: `admin_dependency = Depends(require_admin)` on each admin route or on the router level.
  - For router-level dependency, use: `router = APIRouter(dependencies=[Depends(require_admin)])`.
  - Keep the `ADMIN_API_KEY` env var for backward compatibility during transition — add a fallback: if the `Authorization` header is missing AND `X-Admin-Key` is present AND matches `settings.admin_api_key`, still allow the request. Log a deprecation warning. Remove this fallback in a subsequent PR.
  - Update the OpenAPI docs: remove the padlock icon for admin routes that used the API key header.

### Step 7: Add required packages and configuration
- **Action:** Update dependencies and settings.
- **Files:** `services/backend/requirements.txt`, `services/backend/core/config.py`, `.env.example`
- **Details:**
  - Add to `requirements.txt`:
    - `pyjwt>=2.8.0`
    - `passlib[bcrypt]>=1.7.4`
    - `bcrypt>=4.0.0` (explicit bcrypt for passlib)
  - Add to `Settings` in `config.py`:
    - `jwt_secret_key: str` — read from env `JWT_SECRET_KEY`
    - `jwt_algorithm: str = "HS256"` — env `JWT_ALGORITHM`
    - `jwt_access_token_expire_minutes: int = 30` — env `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`
    - `jwt_refresh_token_expire_days: int = 7` — env `JWT_REFRESH_TOKEN_EXPIRE_DAYS`
  - Add to `.env.example`:
    - `JWT_SECRET_KEY=` with comment "Generate with: openssl rand -hex 32"
    - `JWT_ALGORITHM=HS256`
    - `JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30`
    - `JWT_REFRESH_TOKEN_EXPIRE_DAYS=7`

### Step 8: Wire auth router into main app
- **Action:** Include the auth router in the FastAPI app.
- **Files:** `services/backend/main.py`
- **Details:**
  - Add: `from routers import auth`
  - Add: `app.include_router(auth.router, prefix="/auth", tags=["auth"])`
  - Ensure the auth router is placed before the admin router in import order (convention).

### Step 9: Write auth tests
- **Action:** Create comprehensive test file for authentication.
- **Files:** `services/backend/tests/test_auth.py`
- **Details:**
  - Test cases:
    - `test_register_success`: POST `/auth/register` with valid data → 201 + UserResponse with correct fields
    - `test_register_duplicate_email`: POST `/auth/register` twice with same email → 409
    - `test_register_weak_password`: POST `/auth/register` with password < 8 chars → 422 (validation)
    - `test_login_success`: register, then POST `/auth/login` → 200 + TokenResponse with access_token and refresh_token
    - `test_login_invalid_password`: register with valid email, wrong password → 401
    - `test_login_nonexistent_email`: POST `/auth/login` with unregistered email → 401
    - `test_login_inactive_user`: create user with `is_active=False`, try login → 403
    - `test_access_protected_without_token`: GET `/auth/me` without Authorization header → 401
    - `test_access_protected_with_invalid_token`: GET `/auth/me` with `Authorization: Bearer invalid-token` → 401
    - `test_access_protected_with_expired_token`: create token with `exp` in the past → 401 with message "Token has expired"
    - `test_refresh_token_success`: login, POST `/auth/refresh` with valid refresh token → 200 + new tokens
    - `test_refresh_token_reuse`: login, refresh twice with same token → second request returns 401 (reuse detected)
    - `test_access_admin_as_student`: register as student, try to access admin endpoint → 403
    - `test_access_admin_as_admin`: register as admin, access admin endpoint → 200
    - `test_cors_not_exposing_auth_headers`: verify CORS headers on auth responses
  - Use fixtures from `conftest.py`:
    - Add fixture `auth_token(student_user)` that registers a user and returns a valid access token.
    - Add fixture `admin_token(admin_user)` that returns a valid admin access token.

## Acceptance Criteria

- [ ] `User` model exists with all required fields and unique email index.
- [ ] `POST /auth/register` creates a user with bcrypt-hashed password.
- [ ] `POST /auth/login` returns JWT access token (30min) + refresh token (7d).
- [ ] `POST /auth/refresh` implements token rotation and detects reuse.
- [ ] `require_admin` dependency blocks non-admin users with 403.
- [ ] All admin routes migrated from `X-Admin-Key` to JWT (with backward compat fallback).
- [ ] Alembic migration creates `users` and `refresh_tokens` tables.
- [ ] All 15+ auth tests pass.
- [ ] `.env.example` documents `JWT_SECRET_KEY` and related vars.
- [ ] Admin router shows proper OpenAPI auth scheme (Bearer) in docs.

## Risks & Notes

- **Token storage on frontend:** Decisions about whether to use httpOnly cookies vs localStorage affect how the backend sets tokens. Recommend starting with Bearer tokens returned in JSON body (simplest) and letting the frontend decide storage strategy.
- **Backward compat:** Keep the `X-Admin-Key` fallback for exactly one release cycle. Add a `WARNING` log message on each use so admins know to migrate.
- **Rate limiting:** Auth endpoints (especially login) need rate limiting (5 req/min) to prevent brute force. This is addressed in plan 05.
- **Existing `Student` model:** There is an existing `Student` model with `name`, `email`, `language`, `created_at`. The new `User` model overlaps partially. Decide on migration strategy:
  - Option A: Add `user_id` FK to existing `Student` table, create users for existing students.
  - Option B: Deprecate `Student` model entirely and use `User` with `role=student`.
  - **Recommendation:** Option A for backward compatibility. The `/sessions/students` endpoint can auto-create a `User` when a student is created.
- **Password strength:** Enforce minimum 8 characters server-side. Consider adding zxcvbn for password strength estimation in the future.
- **Test DB:** Tests use SQLite which doesn't support PostgreSQL enums natively. Ensure the `UserRole` enum uses `String` type in the column definition or use `SAEnum` with `create_constraint=False` for SQLite compatibility.

## Dependencies

- `pyjwt>=2.8.0` — JWT encoding/decoding
- `passlib[bcrypt]>=1.7.4` — password hashing
- `bcrypt>=4.0.0` — bcrypt implementation
- Alembic — migration tool (already in requirements.txt)
- Python's `secrets` module (stdlib) — for generating `JWT_SECRET_KEY`
