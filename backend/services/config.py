"""
Snowsky Config Service — extracted from batchdl.py ConfigManager.

Manages persistent JSON configuration with defaults and first-run wizard.
"""
import json
import os
from pathlib import Path

DEFAULT_CONFIG = {
    "music_folder": os.path.join(str(Path.home()), "Music", "batchdl"),
    "mp3_mode": False,
    "music_only": False,
    "lyrics_mode": True,
    "cookies_browser": None,
    "max_workers": 2,
    "parallel_mode": True,
    "filename_template": "%(playlist_index|00|)s %(title)s.%(ext)s",
}

# Resolve paths relative to project root (one level up from backend/)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "config.json")


def get_config_path() -> str:
    return _CONFIG_PATH


def load_config() -> dict:
    """Load config from disk, merging with defaults for any missing keys."""
    config = dict(DEFAULT_CONFIG)
    if os.path.exists(_CONFIG_PATH):
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                user_config = json.load(f)
            config.update(user_config)
        except (json.JSONDecodeError, IOError):
            pass
    return config


def save_config(config: dict) -> None:
    """Persist config to disk."""
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)


def update_config(updates: dict) -> dict:
    """Apply partial updates and save. Returns the full updated config."""
    config = load_config()
    config.update(updates)
    save_config(config)
    return config


def get_download_root(config: dict | None = None) -> str:
    """Get the music download root folder, creating it if needed."""
    if config is None:
        config = load_config()
    root = config.get("music_folder", DEFAULT_CONFIG["music_folder"])
    os.makedirs(root, exist_ok=True)
    return root


def find_cookies_file() -> str | None:
    """Auto-detect cookies.txt next to the project root."""
    cookies_path = os.path.join(_PROJECT_ROOT, "cookies.txt")
    if os.path.exists(cookies_path):
        return cookies_path
    return None
