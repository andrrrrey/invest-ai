# What To Do When a Task Is Completed

1. **Verify backend still starts**: `uvicorn app.main:app --reload --port 8000` (or check Docker logs)
2. **Check for import errors**: Python syntax is validated on startup
3. **No automated tests exist** — manual testing via Swagger UI (`/api/docs`) or browser
4. **If DB schema changed**: run `alembic revision --autogenerate -m "..."` + `alembic upgrade head`
5. **If frontend changed**: refresh browser (no build step needed)
6. **If Docker Compose used**: `docker compose build backend && docker compose up -d --no-deps backend`
7. **No linter/formatter to run** — follow PEP 8 manually; consider `ruff` if added in future
8. **Commit** changes with a descriptive message following the repo's style
