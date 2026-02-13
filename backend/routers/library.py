"""
Library Router — browse and search the music library.
"""
from fastapi import APIRouter

from backend.models import LibraryResponse, LibraryItem
from backend.services import config as config_svc
from backend.services import library as library_svc

router = APIRouter(prefix="/api/library", tags=["library"])


@router.get("", response_model=LibraryResponse)
async def get_library():
    """Get the full library as a flat list of Artist/Album items."""
    root = config_svc.get_download_root()
    items = library_svc.scan_library(root)

    artists = set()
    total_tracks = 0
    response_items = []

    for item in items:
        artists.add(item.artist)
        total_tracks += item.tracks
        response_items.append(LibraryItem(
            artist=item.artist,
            album=item.album,
            path=item.path,
            tracks=item.tracks,
            track_files=item.track_files,
            cover_url=item.cover_url,
        ))

    return LibraryResponse(
        total_artists=len(artists),
        total_albums=len(response_items),
        total_tracks=total_tracks,
        items=response_items,
    )


@router.get("/tree")
async def get_library_tree():
    """Get the library as a nested Artist → Album → Tracks tree."""
    root = config_svc.get_download_root()
    return library_svc.get_library_tree(root)


@router.post("/refresh")
async def refresh_library():
    """Force a library rescan and return updated stats."""
    root = config_svc.get_download_root()
    items = library_svc.scan_library(root)
    return {
        "total_artists": len(set(i.artist for i in items)),
        "total_albums": len(items),
        "total_tracks": sum(i.tracks for i in items),
    }
