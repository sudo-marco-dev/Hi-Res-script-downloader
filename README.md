# 🎵 Snowsky Retro Mini Music Manager (Batch Downloader)

A robust, terminal-based music downloader and manager powered by `yt-dlp`. Features batch downloading from playlists, metadata embedding, lyrics fetching, and a retro TUI.

## 🚀 Features
- **Batch Download**: Supports YouTube Music playlists, albums, and single tracks.
- **High Quality**: Downloads OPUS/AAC and converts to FLAC or MP3 (320kbps).
- **Metadata**: Automatically embeds Cover Art, Artist, Title, and Album tags.
- **Lyrics**: Fetches synced lyrics (`.lrc`) from LRCLIB.
- **Retro UI**: A beautiful, text-based interface for easy management.

---

## 🛠️ Installation & Setup

### 1. Install Prerequisites
You need the following installed on your system:

- **Python 3.8+**: [Download Here](https://www.python.org/downloads/)
- **Node.js (LTS Version)**: **REQUIRED** for YouTube signature solving.
  - ⚠️ **IMPORTANT**: Do NOT use the "Current" (v25+) version. Use **LTS** (v24.x).
  - Install via Winget: `winget install -e --id OpenJS.NodeJS.LTS`
- **FFmpeg**: Required for audio conversion and metadata.
  - Install via Winget: `winget install -e --id Gyan.FFmpeg`

### 2. Install Python Dependencies
Open your terminal in this folder and run:
```powershell
pip install -r requirements.txt
```
*Note: It is recommended to use a virtual environment (`.venv`).*

### 3. Setup Cookies (Crucial for Music)
To avoid "403 Forbidden" errors and age-restricted content issues:
1.  Install a "Get cookies.txt LOCALLY" extension for your browser.
2.  Log in to [music.youtube.com](https://music.youtube.com).
3.  Export your cookies as `cookies.txt`.
4.  Place `cookies.txt` in this script's folder.

---

## 📖 Usage

Run the script using Python:
```powershell
python batchdl.py
```
*Or if using the virtual environment:*
```powershell
.venv\Scripts\python.exe batchdl.py
```

### Menu Options
- **1**: Download single URL (Artist/Album auto-detection).
- **2**: Download a Playlist URL.
- **4**: Batch mode (Download multiple URLs from input).
- **f**: Toggle "Music Only" filter (filters out video-only content).
- **m**: Toggle Format (FLAC / MP3).

---

## 🔧 Troubleshooting

### ❌ "HTTP Error 403: Forbidden"
**Cause**: YouTube has blocked your request or your cookies are invalid.
**Fix**:
1.  Delete the old `cookies.txt`.
2.  Get a fresh `cookies.txt` from your browser (make sure you are logged in).
3.  Restart the script.

### ❌ "Signature solving failed" / "Requested format is not available"
**Cause**: Missing or incompatible Node.js. `yt-dlp` needs Node.js to decrypt YouTube's latest signature challenges.
**Fix**:
1.  Ensure Node.js is installed: `node --version`.
2.  **Downgrade to LTS**: If you are on the "Current" version (e.g., v25.x), uninstall it and install the **LTS** version (v24.x or v22.x).
    ```powershell
    winget uninstall OpenJS.NodeJS
    winget install OpenJS.NodeJS.LTS
    ```
3.  **Restart your terminal** after installing Node.js.

### ❌ "ImportError: No module named 'requests' / 'rich'"
**Cause**: Dependencies are not installed in the current environment.
**Fix**:
Run `pip install -r requirements.txt`. If you are using a virtual environment, ensure it is activated or call the python executable inside `.venv`.
