"""
Snowsky Cover Pipeline — extracted from batchdl.py MusicDownloader cover methods.

Handles: thumbnail discovery → ffmpeg crop 500×500 → embed into FLAC/MP3.
Snowsky spec: 500×500 JPEG, center-cropped (no black bars).
"""
import os
import glob
import subprocess
import logging
import time

FFMPEG_CMD = "ffmpeg"

logger = logging.getLogger("snowsky.cover")


def safe_file_op(func, *args, retries=3, delay=0.5, **kwargs):
    """Retry file operations to handle WinError 32 (file in use)."""
    for attempt in range(retries):
        try:
            return func(*args, **kwargs)
        except PermissionError:
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                raise


def _run_ffmpeg(cmd: list[str]) -> None:
    """Run an ffmpeg command, suppressing output unless error."""
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def make_square_500(img_in: str, img_out: str) -> None:
    """
    Center-crop image to square, scale to 500×500 JPEG.
    NO black bars — crops the longer dimension.
    """
    vf = "crop='min(iw,ih):(min(iw,ih))',scale=500:500"
    cmd = [FFMPEG_CMD, "-y", "-i", img_in, "-vf", vf, "-q:v", "1", img_out]
    _run_ffmpeg(cmd)


def embed_cover_into_flac(flac_path: str, cover_jpg_500: str) -> None:
    """Re-mux FLAC with 500×500 cover as attached picture."""
    tmp = flac_path + ".tmp.flac"
    cmd = [
        FFMPEG_CMD, "-y",
        "-i", flac_path,
        "-i", cover_jpg_500,
        "-map", "0:a",
        "-map", "1:v",
        "-c:a", "copy",
        "-c:v", "mjpeg",
        "-disposition:v:0", "attached_pic",
        tmp,
    ]
    _run_ffmpeg(cmd)
    safe_file_op(os.replace, tmp, flac_path)


def _find_thumbnail(base_no_ext: str) -> str | None:
    """Find best thumbnail for a track (by basename without extension)."""
    for ext in (".jpg", ".webp", ".png"):
        p = base_no_ext + ext
        if os.path.exists(p):
            return p
    return None


def _find_fallback_cover(folder: str) -> str | None:
    """Look for folder/cover/front/album.jpg as fallback."""
    for name in ("folder.jpg", "cover.jpg", "front.jpg", "album.jpg"):
        p = os.path.join(folder, name)
        if os.path.exists(p):
            return p
    return None


def process_single_file_cover(filepath: str) -> bool:
    """
    Process cover art for a single FLAC or MP3 file:
    1. Find matching thumbnail or fallback
    2. Crop to 500×500 JPEG
    3. Embed into audio file
    4. Clean up temporary images

    Returns True if cover was embedded successfully.
    """
    base = os.path.splitext(filepath)[0]
    folder = os.path.dirname(filepath)

    thumb = _find_thumbnail(base) or _find_fallback_cover(folder)
    if not thumb:
        return False

    cover500 = base + ".cover500.jpg"
    try:
        make_square_500(thumb, cover500)
        embed_cover_into_flac(filepath, cover500)
        logger.info(f"Embedded 500×500 cover → {os.path.basename(filepath)}")
        return True
    except Exception as e:
        logger.error(f"Cover embed failed for {os.path.basename(filepath)}: {e}")
        return False
    finally:
        # Clean up temp files
        if os.path.exists(cover500):
            safe_file_op(os.remove, cover500)
        for ext in (".jpg", ".webp", ".png"):
            p = base + ext
            if os.path.exists(p):
                try:
                    safe_file_op(os.remove, p)
                except Exception:
                    pass


def fix_all_covers(folder: str) -> dict:
    """
    Process covers for all audio files in a folder.
    Returns {"processed": N, "success": N, "failed": N}.
    """
    stats = {"processed": 0, "success": 0, "failed": 0}

    for pattern in ("*.flac", "*.mp3"):
        for filepath in sorted(glob.glob(os.path.join(folder, pattern))):
            stats["processed"] += 1
            if process_single_file_cover(filepath):
                stats["success"] += 1
            else:
                stats["failed"] += 1

    return stats
