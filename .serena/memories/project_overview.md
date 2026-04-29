# Project Overview: invest-ai

## Purpose
Web application for managing investment projects with AI analysis and financial modelling ("Инвестиционный процессор"). Users create projects, run financial calculations (NPV, IRR, DCF, DPP, PI, LTV/CAC), and get AI-generated descriptions, risks, and anomaly analysis via Claude.

## Tech Stack
- **Backend**: Python 3.11 · FastAPI 0.115 · SQLAlchemy 2 · Pydantic v2 · Alembic
- **Database**: SQLite (dev) / PostgreSQL (prod)
- **AI**: Anthropic Claude API via `openai` SDK compat (`claude-sonnet-4-6`)
- **Financial calculations**: `numpy-financial` (backend) · vanilla JS (frontend, real-time)
- **Frontend**: HTML5 · Alpine.js 3 · Font Awesome · plain JS (`frontend/js/finance.js`)
- **Web server**: Nginx (reverse proxy + static files)
- **Containerisation**: Docker · Docker Compose
- **Auth**: JWT (python-jose + passlib/bcrypt)
- **Export**: WeasyPrint (PDF) · openpyxl (Excel)

## Project Status Flow
`draft → pending_approval → approved | rejected`

## Key Environment Variables
- `ANTHROPIC_API_KEY` — required for AI features
- `DATABASE_URL` — defaults to SQLite
- `SECRET_KEY` — required in production (JWT signing)
- `CORS_ORIGINS` — allowed origins list
