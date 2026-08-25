from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import logging
import os
import time

AVATARS_DIR = os.environ.get("AVATARS_DIR", "/data/avatars")
ATTACHMENTS_DIR = os.environ.get("ATTACHMENTS_DIR", "/data/attachments")

from .config import settings
from .database import init_db
from .logging_config import setup_logging

# Configure structured JSON logging as early as possible.
setup_logging(os.environ.get("LOG_LEVEL", "INFO"))
_request_logger = logging.getLogger("hermes.request")
from .api.v1 import projects, finance, ai, stats
from .api.v1 import settings as settings_router
from .api.v1 import auth as auth_router
from .api.v1 import users as users_router
from .api.v1 import export as export_router
from .api.v1 import comments as comments_router
from .api.v1 import attachments as attachments_router
from .api.v1 import notifications as notifications_router
from .api.v1 import tranches as tranches_router
from .api.v1 import fact as fact_router
from .api.v1 import mattermost as mattermost_router

app = FastAPI(
    title="Инвестиционный процессор",
    description="API бэкенд для управления инвестиционными проектами",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """Сквозное логирование запросов: метод, путь, статус, длительность.

    Тело запроса НЕ логируется (может содержать конфиденциальные данные).
    """
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        _request_logger.exception(
            "request failed",
            extra={"request": {
                "method": request.method,
                "path": request.url.path,
                "ms": duration_ms,
            }},
        )
        raise
    duration_ms = round((time.perf_counter() - start) * 1000, 1)
    _request_logger.info(
        "request",
        extra={"request": {
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "ms": duration_ms,
        }},
    )
    return response

# API routes
app.include_router(auth_router.router, prefix="/api/v1")
app.include_router(users_router.router, prefix="/api/v1")
app.include_router(projects.router, prefix="/api/v1")
app.include_router(finance.router, prefix="/api/v1")
app.include_router(ai.router, prefix="/api/v1")
app.include_router(stats.router, prefix="/api/v1")
app.include_router(settings_router.router, prefix="/api/v1")
app.include_router(export_router.router, prefix="/api/v1")
app.include_router(comments_router.router, prefix="/api/v1")
app.include_router(attachments_router.router, prefix="/api/v1")
app.include_router(notifications_router.router, prefix="/api/v1")
app.include_router(tranches_router.router, prefix="/api/v1")
app.include_router(fact_router.router, prefix="/api/v1")
app.include_router(mattermost_router.router, prefix="/api/v1")


@app.on_event("startup")
def on_startup():
    # Fail fast on insecure production configuration (default SECRET_KEY, CORS *, ...)
    settings.validate_for_production()
    init_db()


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "1.0.0"}


# Serve avatar uploads
os.makedirs(AVATARS_DIR, exist_ok=True)
app.mount("/avatars", StaticFiles(directory=AVATARS_DIR), name="avatars")

# Ensure attachments directory exists (served via authenticated endpoint, not static mount)
os.makedirs(ATTACHMENTS_DIR, exist_ok=True)

# Serve frontend static files in production
frontend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
if os.path.isdir(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
