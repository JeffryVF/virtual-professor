# Repository Guidelines

## Project Structure & Module Organization

- `services/backend/` contains the FastAPI API, domain services, SQLAlchemy models, and pytest suite.
- `services/frontend/` is the Next.js app; UI code lives in `src/app`, `src/components`, and `src/lib`.
- `services/kokoro/` wraps the TTS service.
- `config/` holds reverse-proxy configuration, `docs/` contains supporting notes, and `data/` is for local persistent volumes.

## Build, Test, and Development Commands

- `docker compose up -d` starts the full stack with the dev overrides from `docker-compose.override.yml`.
- `docker compose down` stops the stack; add `-v` only when you want to wipe local data.
- `cd services/backend && pytest` runs the backend tests in `services/backend/tests/`.
- `cd services/frontend && npm run dev` starts the Next.js app in watch mode.
- `cd services/frontend && npm run build` verifies the production frontend build.

## Coding Style & Naming Conventions

- Python uses 4-space indentation, explicit module paths, and `test_*.py` filenames.
- TypeScript/React uses 2-space indentation and component-based filenames such as `ProfessorCard.tsx`.
- Keep names descriptive and domain-based: routers in `routers/`, orchestration code in `services/`, schema objects in `models/schemas.py`.
- No formatter or linter is enforced in the repo, so match the surrounding style exactly.

## Testing Guidelines

- Backend coverage lives under `services/backend/tests/` and uses pytest; keep new tests close to the behavior they cover.
- Prefer `test_<feature>.py` and `test_<scenario>` names so failures are easy to scan.
- When changing API behavior, verify both the happy path and the error path.

## Commit & Pull Request Guidelines

- Commit history follows Conventional Commits with scopes, e.g. `feat(rag): ...`, `feat(admin): ...`, `fix(memory): ...`.
- Keep commits focused and do not add AI attribution or `Co-Authored-By` lines.
- PRs should explain what changed, how it was tested, and include screenshots for frontend updates or logs for backend fixes.

## Configuration & Environment Tips

- Copy `.env.example` to `.env` before running locally.
- The system depends on Dockerized services plus external keys such as `LIVEAVATAR_API_KEY` and `ADMIN_API_KEY`.
