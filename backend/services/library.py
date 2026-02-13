"""
Snowsky Library Service — extracted from batchdl.py LibraryManager.

Recursively scans the music folder and groups tracks by Artist/Album.
"""
import os
from pathlib import Path
from dataclasses import dataclass, field

AUDIO_EXTENSIONS = {".mp3", ".flac", ".m4a", ".wav", ".ogg"}
COVER_EXTENSIONS = {".jpg", ".jpeg", ".png"}


@dataclass
class LibraryItem:
    artist: str
    album: str
    path: str
    tracks: int
    cover_url: str | None = None
    track_files: list[str] = field(default_factory=list)


def scan_library(root_path: str) -> list[LibraryItem]:
    """
    Recursively scan root_path for folders containing audio files.
    Returns a sorted list of LibraryItems grouped by Artist/Album.
    """
    root = Path(root_path)
    items: list[LibraryItem] = []

    if not root.exists():
        return items

    for dirpath, _dirs, files in os.walk(root):
        path_obj = Path(dirpath)
        audio_files = [f for f in files if Path(f).suffix.lower() in AUDIO_EXTENSIONS]

        if not audio_files:
            continue
        if path_obj == root:
            continue

        # Determine Artist/Album
        album_name = path_obj.name
        parent_name = path_obj.parent.name

        if parent_name == "Playlists":
            artist_name = "Playlist"
        elif path_obj.parent == root:
            # Loose files directly under Artist folder
            artist_name = album_name
            album_name = "Singles"
        else:
            artist_name = parent_name
            album_name = album_name

        # Find cover image
        cover_url = None
        for f in files:
            if Path(f).suffix.lower() in COVER_EXTENSIONS:
                # We mounted root at /covers, so relative path from root needed
                try:
                    rel_path = path_obj.relative_to(root)
                    # Convert backslash to forward slash for URL
                    rel_path_str = str(rel_path / f).replace("\\", "/")
                    cover_url = f"/covers/{rel_path_str}"
                    break
                except ValueError:
                    pass

        items.append(LibraryItem(
            artist=artist_name,
            album=album_name,
            path=str(path_obj),
            tracks=len(audio_files),
            track_files=sorted(audio_files),
            cover_url=cover_url,
        ))

    items.sort(key=lambda x: (x.artist.lower(), x.album.lower()))
    return items


def get_library_tree(root_path: str) -> dict:
    """
    Returns a nested dict for tree rendering.
    """
    items = scan_library(root_path)
    tree: dict = {}
    for item in items:
        if item.artist not in tree:
            tree[item.artist] = {}
        tree[item.artist][item.album] = {
            "path": item.path,
            "tracks": item.tracks,
            "files": item.track_files,
            "cover": item.cover_url,
        }
    return tree


def find_album_path(root_path: str, artist: str, album: str) -> str | None:
    """Find the filesystem path for a specific Artist/Album combo."""
    items = scan_library(root_path)
    for item in items:
        if item.artist == artist and item.album == album:
            return item.path
    return None
