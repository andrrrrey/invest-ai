# Codebase Structure

```
invest-ai/
├── backend/
│   ├── app/
│   │   ├── main.py               # FastAPI app, CORS, router includes, static mounts
│   │   ├── config.py             # Settings (pydantic-settings, reads .env)
│   │   ├── database.py           # SQLAlchemy engine, sessions, init_db()
│   │   ├── auth.py               # JWT helpers
│   │   ├── settings_store.py     # Per-user settings persistence
│   │   ├── models/
│   │   │   ├── project.py        # ORM model: Project
│   │   │   └── user.py           # ORM model: User
│   │   ├── schemas/
│   │   │   ├── project.py        # Pydantic DTOs: ProjectCreate/Update/Read
│   │   │   ├── finance.py        # FinancialModelInput · FinancialMetrics
│   │   │   └── user.py           # UserCreate/Read/Update
│   │   ├── api/v1/
│   │   │   ├── projects.py       # CRUD + status change
│   │   │   ├── finance.py        # POST /finance/calculate
│   │   │   ├── ai.py             # generate-description, generate-risks, analyze
│   │   │   ├── auth.py           # login/register/refresh
│   │   │   ├── users.py          # user profile management
│   │   │   ├── stats.py          # portfolio KPI aggregates
│   │   │   ├── settings.py       # user settings CRUD
│   │   │   └── export.py         # PDF/Excel export
│   │   └── services/
│   │       ├── finance_service.py  # NPV, IRR, DCF, DPP, PI, LTV/CAC logic
│   │       ├── ai_service.py       # Claude API wrapper
│   │       ├── export_pdf.py       # WeasyPrint PDF generation
│   │       ├── export_excel.py     # openpyxl Excel generation
│   │       └── email_service.py    # Email notifications
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── main.html                 # Dashboard (KPI + recent projects)
│   ├── new.html                  # 5-step project creation wizard (Alpine.js)
│   ├── project-list.html         # Portfolio with filters
│   ├── project.html              # Project detail card
│   ├── export.html               # Export reports
│   ├── login.html / register.html
│   ├── profile.html / users.html / settings.html
│   └── js/
│       └── finance.js            # Real-time financial engine (vanilla JS)
├── nginx/
│   └── nginx.conf                # Reverse proxy + static serving
├── docker-compose.yml
├── .env.example
└── README.md
```
