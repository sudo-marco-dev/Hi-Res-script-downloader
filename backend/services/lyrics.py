"""
Snowsky Lyrics Service — extracted from batchdl.py LRCFetcher.

Fetches synced lyrics (.lrc) from LRCLIB using ffprobe metadata extraction
with multi-strategy artist/title fallbacks.
"""
import os
import re
import json
import subprocess
import logging
import shutil

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

AUDIO_EXTENSIONS = {".mp3", ".flac", ".m4a", ".wav", ".ogg"}
LRCLIB_BASE = "https://lrclib.net/api"

logger = logging.getLogger("snowsky.lyrics")


def _find_ffprobe() -> str | None:
    """Find ffprobe in PATH or common Windows locations."""
    if shutil.which("ffprobe"):
        return "ffprobe"

    # Check LOCALAPPDATA for WinGet-installed ffmpeg
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if local_appdata:
        import glob
        pattern = os.path.join(
            local_appdata, "Microsoft", "WinGet", "Packages", "**", "ffprobe.exe"
        )
        matches = glob.glob(pattern, recursive=True)
        if matches:
            return matches[0]

    return None


def get_metadata(filepath: str) -> dict:
    """
    Extract Artist, Title, Album from audio file using ffprobe.
    Falls back to filename parsing if tags are missing.

    Returns: {"artist": str, "title": str, "album": str}
    """
    result = {"artist": "", "title": "", "album": ""}
    ffprobe = _find_ffprobe()

    if ffprobe:
        try:
            cmd = [
                ffprobe, "-v", "quiet",
                "-print_format", "json",
                "-show_format", filepath,
            ]
            output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=10)
            data = json.loads(output)
            tags = data.get("format", {}).get("tags", {})

            # Case-insensitive tag extraction
            for key, val in tags.items():
                kl = key.lower()
                if kl == "artist":
                    result["artist"] = val
                elif kl == "title":
                    result["title"] = val
                elif kl == "album":
                    result["album"] = val
        except Exception as e:
            logger.debug(f"ffprobe failed for {filepath}: {e}")

    # Fallback: parse filename
    if not result["title"]:
        basename = os.path.splitext(os.path.basename(filepath))[0]
        # Remove track number prefix (e.g. "01 Song Name" → "Song Name")
        cleaned = re.sub(r"^\d+[\s._-]+", "", basename)
        result["title"] = cleaned

    return result


def _get_artist_candidates(artist_raw: str) -> list[str]:
    """Generate artist name variants to try against LRCLIB."""
    candidates = [artist_raw]

    # Try first artist if multiple (feat., &, /)
    for sep in [" feat.", " ft.", " feat ", " ft ", " & ", " / ", ", ", " x "]:
        if sep.lower() in artist_raw.lower():
            idx = artist_raw.lower().index(sep.lower())
            first = artist_raw[:idx].strip()
            if first and first not in candidates:
                candidates.append(first)

    return candidates


def fetch_lrc(
    artist: str,
    title: str,
    album: str,
    save_path: str,
) -> bool:
    """
    Fetch synced LRC from LRCLIB with fallback search strategies.
    Saves to save_path (.lrc file).

    Returns True if lyrics were saved successfully.
    """
    if not HAS_REQUESTS:
        logger.warning("requests library not installed — cannot fetch lyrics")
        return False

    session = requests.Session()

    # Clean title: remove parenthetical suffixes
    title_clean = re.sub(r"\s*[\(\[](Official.*?|Music.*?|Lyric.*?|Audio.*?)[\)\]]", "", title, flags=re.IGNORECASE).strip()
    title_variants = [title, title_clean] if title != title_clean else [title]
    artist_variants = _get_artist_candidates(artist)

    for art in artist_variants:
        for ttl in title_variants:
            # Strategy 1: Exact GET
            try:
                params = {"artist_name": art, "track_name": ttl}
                if album:
                    params["album_name"] = album
                resp = session.get(f"{LRCLIB_BASE}/get", params=params, timeout=8)
                if resp.status_code == 200:
                    data = resp.json()
                    lrc = data.get("syncedLyrics") or data.get("plainLyrics")
                    if lrc:
                        with open(save_path, "w", encoding="utf-8") as f:
                            f.write(lrc)
                        logger.info(f"Lyrics saved: {os.path.basename(save_path)}")
                        return True
            except Exception:
                pass

            # Strategy 2: Search endpoint
            try:
                resp = session.get(
                    f"{LRCLIB_BASE}/search",
                    params={"artist_name": art, "track_name": ttl},
                    timeout=8,
                )
                if resp.status_code == 200:
                    results = resp.json()
                    for item in results:
                        lrc = item.get("syncedLyrics") or item.get("plainLyrics")
                        if lrc:
                            with open(save_path, "w", encoding="utf-8") as f:
                                f.write(lrc)
                            logger.info(f"Lyrics saved (search): {os.path.basename(save_path)}")
                            return True
            except Exception:
                pass

    logger.debug(f"No lyrics found for {artist} - {title}")
    return False


def scan_folder_for_lyrics(folder_path: str) -> dict:
    """
    Scan a folder for audio files and fetch lyrics for those missing .lrc files.
    Returns {"scanned": N, "fetched": N, "skipped": N, "failed": N}.
    """
    stats = {"scanned": 0, "fetched": 0, "skipped": 0, "failed": 0}

    if not os.path.isdir(folder_path):
        return stats

    for filename in sorted(os.listdir(folder_path)):
        ext = os.path.splitext(filename)[1].lower()
        if ext not in AUDIO_EXTENSIONS:
            continue

        stats["scanned"] += 1
        filepath = os.path.join(folder_path, filename)
        lrc_path = os.path.splitext(filepath)[0] + ".lrc"

        if os.path.exists(lrc_path):
            stats["skipped"] += 1
            continue

        meta = get_metadata(filepath)
        if not meta["title"]:
            stats["failed"] += 1
            continue

        if fetch_lrc(meta["artist"], meta["title"], meta["album"], lrc_path):
            stats["fetched"] += 1
        else:
            stats["failed"] += 1

    return stats
