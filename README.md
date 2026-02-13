# Snowsky Retro Mini Music Manager (batchdl)

A powerful, terminal-based music downloader and library manager designed to fetch high-quality audio from YouTube and YouTube Music. It automatically handles metadata, cover art resizing, and lyrics fetching.

## Features

*   **High-Quality Downloads**: Supports **FLAC** and **MP3** formats.
*   **Smart Metadata**: Automatically tags files with Artist, Title, and Album.
*   **Cover Art**: Embeds 500x500 square cover art into files.
*   **Lyrics Integration**: Built-in fetcher downloads synchronized lyrics (`.lrc`) from LRCLIB.
*   **Library Management**:
    *   Organizes downloads into `Artist/Album/File` structure.
    *   **Tree View**: Visualize your library in the terminal.
    *   **Snowsky Playlists**: Copy tracks from your library to custom playlist folders.
*   **Batch Processing**:
    *   **Parallel Mode**: multithreaded downloads for speed.
    *   **Queueing**: Queue multiple albums for a single artist.
    *   **Playlist Support**: Download entire YouTube playlists.
*   **Junk Cleanup**: Automatically removes temporary `.info.json` and cover image files.

## Prerequisites

### 1. Python Libraries
Install the required Python packages:

```bash
pip install yt-dlp rich requests
```

### 2. External Tools
*   **FFmpeg**: Required for audio conversion and cover art processing.
    *   Download from [ffmpeg.org](https://ffmpeg.org/download.html).
    *   Ensure `ffmpeg` and `ffprobe` are in your system PATH.
*   **yt-dlp**: The script wraps `yt-dlp`. It is recommended to have it installed via pip (as above), but the script can also use a standalone binary if available.

### 3. Optional: Browser Cookies
To download age-restricted content or YouTube Premium quality (if you have an account), you can provide cookies:
*   **Option A (`cookies.txt`)**: Place a Netscape-formatted `cookies.txt` file in the same directory as the script.
*   **Option B (Browser)**: The script supports extracting cookies from your browser (e.g., Firefox, Chrome) if configured in `config.json`.

## Installation

Clone the repository or download the `batchdl.py` script.

## Configuration

On the first run, the script will ask for a **Music Folder**. It will generate a `config.json` file where you can tweak settings:

```json
{
    "music_folder": "C:\\Users\\...\\Music\\batchdl",
    "mp3_mode": false,         // Set true for MP3, false for FLAC
    "music_only": false,       // Filter for "Topic" channels only
    "lyrics_mode": true,       // Fetch lyrics automatically
    "cookies_browser": null,   // e.g. "firefox"
    "max_workers": 2,          // Threads for parallel downloading
    "parallel_mode": true      // Enable/Disable threading
}
```

## Usage

Run the script:

```bash
python batchdl.py
```

### Main Menu Options

1.  **Any URL → Artist/Album**: Download a single video or album. You will be prompted for an output folder name (e.g., "The Beatles/Abbey Road") and the URL.
2.  **Playlist URL**: Download a YouTube playlist into the `Playlists/` folder.
3.  **Snowsky Playlist**: "Copy" tracks from your existing downloaded library into a new Folder/Playlist without duplicating storage (virtual playlist creation style).
4.  **Batch Artist**: Paste multiple album URLs for a single Artist to download them all in a queue.
5.  **View Library**: Shows a tree view of your current downloads.
6.  **Toggle Format**: Switch between FLAC and MP3.
7.  **Music Only Filter**: Toggle `yt-dlp`'s match filter for "music" content.
8.  **Lyrics Download**: Toggle the lyrics fetcher.
9.  **Download Mode**: Toggle between Parallel (fast) and Single-Threaded (safer) modes.

## Troubleshooting

### `WinError 32` (File in use)
*   Occurs if a file is trying to be renamed while still open. The script has built-in retries, but if it persists, try disabling **Parallel Mode** (Option `p` in menu).

### Downloads Failing / 403 Forbidden
*   YouTube throttles automated requests.
*   **Fix**: Update `yt-dlp` (`pip install -U yt-dlp`).
*   **Fix**: Use a `cookies.txt` file.

### Lyrics not finding matches
*   The internal `LRCFetcher` uses fuzzy matching. Ensure your files have correct "Artist - Title" metadata or filenames.
*   It queries `lrclib.net`. Network issues may prevent fetching.

### "Rich library not found"
*   The script runs in a fallback "Legacy Mode" without `rich`, but it looks much better with it. Install it via `pip install rich`.

## License
MIT
