# Code Style and Conventions

## Python (Backend)
- **Type hints**: used throughout on function signatures (Pydantic models enforce types)
- **Docstrings**: minimal — most functions have no docstrings
- **Naming**: `snake_case` for variables/functions/modules, `PascalCase` for classes
- **Pydantic v2**: schemas use `model_config`, `model_validator`, `field_validator`
- **SQLAlchemy 2**: declarative models with `Mapped[...]` type annotations
- **Async**: FastAPI routes are sync (not async) — database calls via sync SQLAlchemy sessions
- **No linter config**: no ruff/flake8/mypy config present — follow PEP 8 manually
- **Imports**: stdlib first, then third-party, then local (relative imports within app package)
- **Error handling**: FastAPI `HTTPException` raised directly in route handlers

## JavaScript (Frontend)
- **Vanilla JS + Alpine.js 3**: no build step, no bundler
- **finance.js**: standalone module loaded via `<script src="js/finance.js">` — exports financial calculation functions used by Alpine.js data
- **Naming**: `camelCase` for JS variables/functions
- **No TypeScript**, no ESLint config

## API design
- REST, versioned under `/api/v1/`
- Pydantic schemas for request/response validation
- Routes grouped by router files, each router has its own prefix

## Git
- Branch naming: `claude/<description>` for AI-generated branches (from recent history)
- Commits merged via PRs
