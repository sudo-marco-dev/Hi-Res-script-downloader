"""
Snowsky Pydantic Models — request/response schemas for the FastAPI backend.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


# ── Enums ──

class AudioFormat(str, Enum):
    FLAC = "flac"
    MP3 = "mp3"


class DownloadStatus(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"  # covers + lyrics
    DONE = "done"
    FAILED = "failed"


# ── Config ──

class ConfigResponse(BaseModel):
    music_folder: str
    mp3_mode: bool
    music_only: bool
    lyrics_mode: bool
    cookies_browser: str | None
    max_workers: int
    parallel_mode: bool
    filename_template: str


class ConfigUpdate(BaseModel):
    """Partial config update — only include fields you want to change."""
    music_folder: str | None = None
    mp3_mode: bool | None = None
    music_only: bool | None = None
    lyrics_mode: bool | None = None
    cookies_browser: str | None = None
    max_workers: int | None = None
    parallel_mode: bool | None = None
    filename_template: str | None = None


# ── Downloads ──

class DownloadRequest(BaseModel):
    """Request to download a single URL."""
    url: str
    folder_name: str
    format: AudioFormat = AudioFormat.FLAC


class BatchDownloadRequest(BaseModel):
    """Request to batch-download multiple albums for an artist."""
    artist: str
    items: list[BatchItem]


class BatchItem(BaseModel):
    album: str
    url: str


class PlaylistDownloadRequest(BaseModel):
    """Request to download a full YouTube/YTM playlist."""
    url: str
    playlist_name: str
    format: AudioFormat = AudioFormat.FLAC


class DownloadProgress(BaseModel):
    """WebSocket progress message sent to frontend."""
    job_id: str
    status: DownloadStatus
    folder: str
    url: str
    percent: float = 0.0
    speed: str = ""
    eta: str = ""
    current_file: str = ""
    error: str | None = None


class DownloadResult(BaseModel):
    """Result of a completed download job."""
    job_id: str
    folder: str
    url: str
    success: bool
    format: AudioFormat
    tracks_downloaded: int = 0
    covers_processed: int = 0
    lyrics_fetched: int = 0
    error: str | None = None
    duration_seconds: float = 0.0


# ── Library ──

class LibraryItem(BaseModel):
    artist: str
    album: str
    path: str
    tracks: int
    cover_url: str | None = None
    track_files: list[str] = Field(default_factory=list)


class LibraryResponse(BaseModel):
    total_artists: int
    total_albums: int
    total_tracks: int
    items: list[LibraryItem]


class LibraryTreeNode(BaseModel):
    """Nested tree for frontend rendering."""
    name: str
    children: list[LibraryTreeNode] | list[str] = Field(default_factory=list)
    path: str | None = None
    tracks: int = 0


# ── Lyrics ──

class LyricsRequest(BaseModel):
    folder_path: str


class LyricsResult(BaseModel):
    scanned: int
    fetched: int
    skipped: int
    failed: int


# ── Cleanup ──

class CleanupResult(BaseModel):
    files_deleted: int
    bytes_freed: int


# ── System ──

class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "2.0.0"
    ffmpeg_available: bool = False
    ytdlp_available: bool = False
    cookies_found: bool = False
    node_available: bool = False
