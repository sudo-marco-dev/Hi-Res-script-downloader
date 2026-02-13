"""
Download Router — trigger downloads and get job status.
WebSocket endpoint for real-time progress updates.
"""
import asyncio
import json
from collections import defaultdict
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.models import (
    DownloadRequest,
    PlaylistDownloadRequest,
    BatchDownloadRequest,
    DownloadResult,
)
from backend.services import config as config_svc
from backend.services import downloader

router = APIRouter(prefix="/api/download", tags=["download"])

# ── In-memory job tracking ──
# In production, use Redis or similar. For a local app, this is fine.
_active_jobs: dict[str, dict] = {}
_ws_clients: list[WebSocket] = []


async def _broadcast(data: dict):
    """Send progress to all connected WebSocket clients."""
    message = json.dumps(data)
    disconnected = []
    for ws in _ws_clients:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        _ws_clients.remove(ws)


def _make_progress_callback(loop: asyncio.AbstractEventLoop):
    """Create a thread-safe progress callback that broadcasts to WebSockets."""
    def callback(data: dict):
        job_id = data.get("job_id", "")
        _active_jobs[job_id] = data
        asyncio.run_coroutine_threadsafe(_broadcast(data), loop)
    return callback


# ── REST Endpoints ──

@router.post("/single")
async def download_single(req: DownloadRequest):
    """
    Download a single URL to a named folder.
    Runs in background, returns job_id for WebSocket tracking.
    """
    cfg = config_svc.load_config()
    root = config_svc.get_download_root(cfg)

    import os
    folder = os.path.join(root, req.folder_name)
    loop = asyncio.get_event_loop()

    async def _run():
        result = await asyncio.to_thread(
            downloader.run_download,
            folder=folder,
            url=req.url,
            fmt=req.format.value,
            music_only=cfg.get("music_only", False),
            lyrics_enabled=cfg.get("lyrics_mode", True),
            filename_template=cfg.get("filename_template", "%(playlist_index|00|)s %(title)s.%(ext)s"),
            on_progress=_make_progress_callback(loop),
        )
        return result

    task = asyncio.create_task(_run())

    return {
        "status": "started",
        "folder": folder,
        "url": req.url,
        "format": req.format.value,
        "message": "Download started. Connect to /ws/progress for real-time updates.",
    }


@router.post("/playlist")
async def download_playlist(req: PlaylistDownloadRequest):
    """Download a full playlist to a named folder under Playlists/."""
    cfg = config_svc.load_config()
    root = config_svc.get_download_root(cfg)

    import os
    folder = os.path.join(root, "Playlists", req.playlist_name)
    loop = asyncio.get_event_loop()

    async def _run():
        return await asyncio.to_thread(
            downloader.run_download,
            folder=folder,
            url=req.url,
            fmt=req.format.value,
            music_only=cfg.get("music_only", False),
            lyrics_enabled=cfg.get("lyrics_mode", True),
            filename_template=cfg.get("filename_template", "%(playlist_index|00|)s %(title)s.%(ext)s"),
            on_progress=_make_progress_callback(loop),
        )

    asyncio.create_task(_run())

    return {
        "status": "started",
        "folder": folder,
        "url": req.url,
        "format": req.format.value,
    }


@router.post("/batch")
async def download_batch(req: BatchDownloadRequest):
    """
    Queue multiple album downloads for an artist.
    Runs in parallel according to config.
    """
    cfg = config_svc.load_config()
    root = config_svc.get_download_root(cfg)

    import os
    queue_items = [
        (os.path.join(root, req.artist, item.album), item.url)
        for item in req.items
    ]

    loop = asyncio.get_event_loop()

    async def _run():
        return await asyncio.to_thread(
            downloader.run_batch_download,
            queue_items=queue_items,
            fmt="mp3" if cfg.get("mp3_mode") else "flac",
            music_only=cfg.get("music_only", False),
            lyrics_enabled=cfg.get("lyrics_mode", True),
            max_workers=cfg.get("max_workers", 2),
            parallel=cfg.get("parallel_mode", True),
            on_progress=_make_progress_callback(loop),
        )

    asyncio.create_task(_run())

    return {
        "status": "started",
        "artist": req.artist,
        "total_items": len(req.items),
    }


@router.get("/jobs")
async def list_jobs():
    """List all active/recent download jobs."""
    return {"jobs": list(_active_jobs.values())}


# ── WebSocket ──

@router.websocket("/ws/progress")
async def ws_progress(ws: WebSocket):
    """
    WebSocket endpoint for real-time download progress.
    Clients receive JSON messages with job_id, status, percent, speed, eta.
    """
    await ws.accept()
    _ws_clients.append(ws)
    try:
        while True:
            # Keep connection alive, client can send pings
            await ws.receive_text()
    except WebSocketDisconnect:
        _ws_clients.remove(ws)
