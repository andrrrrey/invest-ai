# Suggested Commands

## Running the project

### With Docker (recommended)
```bash
docker compose up -d           # start all services
docker compose logs -f backend # stream backend logs
docker compose build backend   # rebuild backend image
docker compose up -d --no-deps backend  # restart only backend
docker compose down            # stop all
```

### Without Docker (local dev)
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run backend (hot-reload)
uvicorn app.main:app --reload --port 8000

# Serve frontend
cd ../frontend && python -m http.server 3000
```

## Database migrations (Alembic)
```bash
cd backend
alembic revision --autogenerate -m "description"
alembic upgrade head
alembic downgrade -1
```

## Testing
No test suite is configured yet (no tests/ directory, no pytest config found).

## Linting / Formatting
No linter or formatter config found (no pyproject.toml, setup.cfg, .flake8, or .ruff.toml).
Recommended if added: `ruff check .` and `ruff format .`

## API docs
- Swagger UI: http://localhost/api/docs  (or http://localhost:8000/docs without Docker)
- Health check: http://localhost/api/health
