from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

from .config import settings
from .database import init_db
from .api.v1 import projects, finance, ai, stats

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

# API routes
app.include_router(projects.router, prefix="/api/v1")
app.include_router(finance.router, prefix="/api/v1")
app.include_router(ai.router, prefix="/api/v1")
app.include_router(stats.router, prefix="/api/v1")


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "1.0.0"}


# Serve frontend static files in production
frontend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
if os.path.isdir(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
