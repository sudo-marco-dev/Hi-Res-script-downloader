"""
Snowsky Download Service — extracted from batchdl.py MusicDownloader.

Core download engine: yt-dlp subprocess → cover pipeline → lyrics → cleanup.
Designed for both CLI and API use with callback-based progress reporting.
"""
import os
import re
import glob
import shutil
import subprocess
import logging
import time
import uuid
import concurrent.futures
from typing import Callable
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from backend.services import config as config_svc
from backend.services import cover as cover_svc
from backend.services import lyrics as lyrics_svc

YT_DLP_CMD = "yt-dlp"

logger = logging.getLogger("snowsky.downloader")


# ── Helpers ──

def clean_url(url: str) -> str:
    """
    Clean URL by removing tracking parameters while preserving
    video/playlist IDs (v, list, index).
    """
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    keep_keys = {"v", "list", "index"}
    clean_params = {k: v[0] for k, v in params.items() if k in keep_keys}
    cleaned = urlunparse((
        parsed.scheme, parsed.netloc, parsed.path,
        parsed.params, urlencode(clean_params), "",
    ))
    return cleaned


def check_ffmpeg() -> bool:
    """Check if ffmpeg is available."""
    if shutil.which("ffmpeg"):
        return True

    # Search WinGet packages
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if local_appdata:
        pattern = os.path.join(
            local_appdata, "Microsoft", "WinGet", "Packages", "**", "ffmpeg.exe"
        )
        matches = glob.glob(pattern, recursive=True)
        if matches:
            ffmpeg_dir = os.path.dirname(matches[0])
            os.environ["PATH"] += os.pathsep + ffmpeg_dir
            return True

    return False


def check_ytdlp() -> bool:
    """Check if yt-dlp is available."""
    return shutil.which("yt-dlp") is not None


def check_node() -> bool:
    """Check if Node.js is available."""
    return shutil.which("node") is not None


# ── yt-dlp Command Builder ──

def build_ytdlp_cmd(
    outtmpl: str,
    url: str,
    fmt: str = "flac",
    music_only: bool = False,
    cookies_file: str | None = None,
    cookies_browser: str | None = None,
) -> list[str]:
    """
    Build the yt-dlp command with all required flags.
    Extracted from MusicDownloader._yt_dlp_cmd().
    """
    cmd = [
        YT_DLP_CMD,
        "--no-warnings",
        "--ignore-errors",
        "--no-cache-dir",
        "--extract-audio",
        "--write-info-json",
        "--add-metadata",
        "--windows-filenames",
        "--js-runtimes", "node",  # Required for YouTube JS signature solving
    ]

    # Cookie config: cookies.txt > cookies_browser
    if cookies_file:
        cmd.extend(["--cookies", cookies_file])
    elif cookies_browser:
        cmd.extend(["--cookies-from-browser", cookies_browser])

    # Music-only filter
    if music_only:
        cmd.extend(["--match-filter", "track"])

    # Audio format
    if fmt == "mp3":
        cmd.extend(["--audio-format", "mp3", "--audio-quality", "0"])
    else:
        cmd.extend(["--audio-format", "flac", "--audio-quality", "0"])

    # Thumbnails
    cmd.extend([
        "--write-thumbnail",
        "--convert-thumbnails", "jpg",
        "--ppa", "ThumbnailsConvertor:-q:v 2",
        "--output", outtmpl,
        url,
    ])
    return cmd


# ── Progress Parsing ──

# Regex: [download]  45.0% of   3.45MiB at    2.00MiB/s ETA 00:01
_PROGRESS_RE = re.compile(
    r"\[download\]\s+(\d+\.?\d*)%\s+of\s+~?(\S+)\s+at\s+(\S+)\s+ETA\s+(\S+)"
)
_SIMPLE_RE = re.compile(r"\[download\]\s+(\d+\.?\d*)%")
_DEST_RE = re.compile(r"\[download\]\s+Destination:\s+(.+)")


def _parse_progress(line: str) -> dict | None:
    """Parse a yt-dlp output line into progress data."""
    match = _PROGRESS_RE.search(line)
    if match:
        return {
            "percent": float(match.group(1)),
            "size": match.group(2),
            "speed": match.group(3),
            "eta": match.group(4),
        }
    simple = _SIMPLE_RE.search(line)
    if simple:
        return {"percent": float(simple.group(1)), "size": "", "speed": "", "eta": ""}

    dest = _DEST_RE.search(line)
    if dest:
        return {"current_file": dest.group(1).strip()}

    return None


# ── Core Download ──

ProgressCallback = Callable[[dict], None]


def run_download(
    folder: str,
    url: str,
    fmt: str = "flac",
    music_only: bool = False,
    lyrics_enabled: bool = True,
    filename_template: str = "%(playlist_index|00|)s %(title)s.%(ext)s",
    on_progress: ProgressCallback | None = None,
    job_id: str | None = None,
) -> dict:
    """
    Execute a full download pipeline:
      1. yt-dlp download
      2. Cover processing (500×500 Snowsky spec)
      3. Lyrics fetching (LRCLIB)
      4. Cleanup (.info.json)

    Args:
        folder: Target folder path
        url: YouTube/YTM URL
        fmt: "flac" or "mp3"
        music_only: Filter to music tracks only
        lyrics_enabled: Fetch lyrics after download
        filename_template: yt-dlp output template
        on_progress: Optional callback(dict) for progress updates
        job_id: Unique job identifier (auto-generated if None)

    Returns:
        dict with keys: job_id, success, tracks, covers, lyrics, error, duration
    """
    if job_id is None:
        job_id = str(uuid.uuid4())[:8]

    os.makedirs(folder, exist_ok=True)
    url = clean_url(url)
    start_time = time.time()

    result = {
        "job_id": job_id,
        "folder": folder,
        "url": url,
        "success": False,
        "tracks": 0,
        "covers": {"processed": 0, "success": 0, "failed": 0},
        "lyrics": {"scanned": 0, "fetched": 0, "skipped": 0, "failed": 0},
        "error": None,
        "duration": 0.0,
    }

    def _emit(status: str, **kwargs):
        if on_progress:
            on_progress({"job_id": job_id, "status": status, "folder": folder, **kwargs})

    # ── Step 1: yt-dlp ──
    _emit("downloading", percent=0)

    cfg = config_svc.load_config()
    cookies_file = config_svc.find_cookies_file()
    outtmpl = os.path.join(folder, filename_template)

    cmd = build_ytdlp_cmd(
        outtmpl=outtmpl,
        url=url,
        fmt=fmt,
        music_only=music_only,
        cookies_file=cookies_file,
        cookies_browser=cfg.get("cookies_browser"),
    )

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                progress_data = _parse_progress(line.strip())
                if progress_data:
                    _emit("downloading", **progress_data)

        remaining, _ = process.communicate()

        if process.returncode != 0:
            out_lower = (remaining or "").lower()
            produced = any(
                f.endswith(".flac") or f.endswith(".mp3")
                for f in os.listdir(folder)
            )
            if "does not match filter" in out_lower:
                logger.warning(f"Filter mismatch for {url}")
            elif "video unavailable" in out_lower or "403" in out_lower:
                logger.warning(f"Unavailable/Forbidden for {url}")
            else:
                logger.error(f"yt-dlp error for {url}: {remaining}")

            if not produced:
                result["error"] = f"yt-dlp failed (exit {process.returncode})"
                result["duration"] = time.time() - start_time
                _emit("failed", error=result["error"])
                return result

    except Exception as e:
        result["error"] = str(e)
        result["duration"] = time.time() - start_time
        logger.error(f"Download exception for {url}: {e}")
        _emit("failed", error=result["error"])
        return result

    # Count downloaded tracks
    audio_exts = {".flac", ".mp3"}
    result["tracks"] = sum(
        1 for f in os.listdir(folder)
        if os.path.splitext(f)[1].lower() in audio_exts
    )

    # ── Step 2: Cover processing ──
    _emit("processing", step="covers")
    result["covers"] = cover_svc.fix_all_covers(folder)

    # ── Step 3: Lyrics ──
    if lyrics_enabled:
        _emit("processing", step="lyrics")
        result["lyrics"] = lyrics_svc.scan_folder_for_lyrics(folder)

    # ── Step 4: Cleanup (.info.json) ──
    _emit("processing", step="cleanup")
    for json_path in glob.glob(os.path.join(folder, "*.info.json")):
        try:
            cover_svc.safe_file_op(os.remove, json_path)
        except Exception:
            pass

    result["success"] = True
    result["duration"] = time.time() - start_time
    _emit("done", tracks=result["tracks"])
    return result


# ── Batch Download ──

def run_batch_download(
    queue_items: list[tuple[str, str]],
    fmt: str = "flac",
    music_only: bool = False,
    lyrics_enabled: bool = True,
    max_workers: int = 2,
    parallel: bool = True,
    on_progress: ProgressCallback | None = None,
) -> dict:
    """
    Download multiple items, optionally in parallel.

    Args:
        queue_items: List of (folder_path, url) tuples
        Other args same as run_download

    Returns:
        dict with keys: total, success, failed, results, duration
    """
    if not queue_items:
        return {"total": 0, "success": 0, "failed": 0, "results": [], "duration": 0.0}

    workers = max_workers if parallel else 1
    start = time.time()
    results = []

    def _worker(folder_url):
        folder, url = folder_url
        return run_download(
            folder=folder,
            url=url,
            fmt=fmt,
            music_only=music_only,
            lyrics_enabled=lyrics_enabled,
            on_progress=on_progress,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = []
        for item in queue_items:
            future = executor.submit(_worker, item)
            futures.append(future)
            if parallel:
                time.sleep(2.0)  # Stagger starts

        for future in concurrent.futures.as_completed(futures):
            try:
                results.append(future.result())
            except Exception as e:
                logger.error(f"Batch worker failed: {e}")
                results.append({"success": False, "error": str(e)})

    success = sum(1 for r in results if r.get("success"))
    return {
        "total": len(queue_items),
        "success": success,
        "failed": len(queue_items) - success,
        "results": results,
        "duration": time.time() - start,
    }
