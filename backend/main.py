"""
Snowsky Backend — FastAPI application entry point.

Run with:
    uvicorn backend.main:app --reload --port 8000

API docs:
    http://localhost:8000/docs  (Swagger)
    http://localhost:8000/redoc (ReDoc)
"""
import shutil
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.models import HealthResponse
from backend.services import config as config_svc
from backend.routers import config as config_router
from backend.routers import library as library_router
from backend.routers import download as download_router
from backend.routers import lyrics as lyrics_router

# ── Logging ──

logging.basicConfig(
    filename="snowsky.log",
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("snowsky")


# ── Lifespan ──

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    logger.info("Snowsky Backend starting up")

    # Ensure download root exists
    config_svc.get_download_root()

    yield

    logger.info("Snowsky Backend shutting down")


# ── App ──

app = FastAPI(
    title="Snowsky Music Manager",
    description="Backend API for the Snowsky music download manager. "
                "Downloads from YouTube/YT Music with Snowsky-spec covers (500×500 JPEG) "
                "and synced lyrics from LRCLIB.",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS — allow the Electron/React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Electron/localhost
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ──

app.include_router(config_router.router)
app.include_router(library_router.router)
app.include_router(download_router.router)
app.include_router(lyrics_router.router)


# ── Static Files (Covers) ──

# Mount the music folder to serve covers
# We need to get the root path. Since config can change, this is a bit tricky for a long-running app if config changes.
# For now, we mount it at startup.
try:
    download_root = config_svc.get_download_root()
    if os.path.exists(download_root):
        app.mount("/covers", StaticFiles(directory=download_root), name="covers")
        logger.info(f"Mounted /covers to {download_root}")
except Exception as e:
    logger.error(f"Failed to mount /covers: {e}")


# ── Health Check ──

@app.get("/api/health", response_model=HealthResponse)
async def health():
    """System health check — verify all dependencies are available."""
    return HealthResponse(
        status="ok",
        version="2.0.0",
        ffmpeg_available=shutil.which("ffmpeg") is not None,
        ytdlp_available=shutil.which("yt-dlp") is not None,
        cookies_found=config_svc.find_cookies_file() is not None,
        node_available=shutil.which("node") is not None,
    )


@app.get("/")
async def root():
    """Root redirect to API docs."""
    return {
        "app": "Snowsky Music Manager",
        "version": "2.0.0",
        "docs": "/docs",
        "health": "/api/health",
        "covers": "/covers",
    }
