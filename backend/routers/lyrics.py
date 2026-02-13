"""
Lyrics Router — fetch and manage .lrc files.
"""
import os
import glob

from fastapi import APIRouter

from backend.models import LyricsRequest, LyricsResult, CleanupResult
from backend.services import config as config_svc
from backend.services import lyrics as lyrics_svc
from backend.services import cover as cover_svc

router = APIRouter(prefix="/api/lyrics", tags=["lyrics"])


@router.post("/scan", response_model=LyricsResult)
async def scan_folder(req: LyricsRequest):
    """Scan a folder for audio files and fetch missing lyrics."""
    import asyncio
    result = await asyncio.to_thread(lyrics_svc.scan_folder_for_lyrics, req.folder_path)
    return LyricsResult(**result)


@router.post("/scan-all", response_model=LyricsResult)
async def scan_all():
    """Scan the entire library for missing lyrics."""
    import asyncio
    root = config_svc.get_download_root()
    totals = {"scanned": 0, "fetched": 0, "skipped": 0, "failed": 0}

    for dirpath, _, files in os.walk(root):
        has_audio = any(
            os.path.splitext(f)[1].lower() in lyrics_svc.AUDIO_EXTENSIONS
            for f in files
        )
        if has_audio:
            result = await asyncio.to_thread(lyrics_svc.scan_folder_for_lyrics, dirpath)
            for key in totals:
                totals[key] += result[key]

    return LyricsResult(**totals)


@router.post("/cleanup", response_model=CleanupResult)
async def cleanup_junk():
    """Recursively delete .info.json files from the library."""
    root = config_svc.get_download_root()
    count = 0
    total_size = 0

    for dirpath, _, files in os.walk(root):
        for f in files:
            if f.endswith(".info.json"):
                path = os.path.join(dirpath, f)
                try:
                    size = os.path.getsize(path)
                    cover_svc.safe_file_op(os.remove, path)
                    count += 1
                    total_size += size
                except Exception:
                    pass

    return CleanupResult(files_deleted=count, bytes_freed=total_size)
