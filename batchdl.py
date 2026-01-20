import os
import subprocess
import sys
import time
import threading
from pathlib import Path
from urllib.parse import urlparse
import shutil
import glob
import re # for title parsing

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# ANSI Colors
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

DOWNLOAD_ROOT = r"C:\Users\marco\Music\batchdl"
YT_DLP_CMD = "yt-dlp"
FFMPEG_CMD = "ffmpeg"

SPINNER = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']

class Spinner:
    def __init__(self):
        self.spinning = False
        self.thread = None

    def start(self, message):
        self.spinning = True
        self.message = message
        self.thread = threading.Thread(target=self._spin, daemon=True)
        self.thread.start()

    def _spin(self):
        i = 0
        while self.spinning:
            sys.stdout.write(f'\r{Colors.OKGREEN}{SPINNER[i % len(SPINNER)]}{Colors.ENDC} {self.message}')
            sys.stdout.flush()
            i += 1
            time.sleep(0.1)

    def stop(self, success=True):
        self.spinning = False
        if self.thread:
            self.thread.join(timeout=0.2)
        status = f"{Colors.OKGREEN}✅ COMPLETE{Colors.ENDC}" if success else f"{Colors.FAIL}❌ FAILED{Colors.ENDC}"
        print(f'\r{status:>20} {self.message}')

def clean_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if 'music.youtube.com' in parsed.netloc:
        query_params = parsed.query.split('&')
        cleaned_params = [p for p in query_params if not p.startswith('si=')]
        return parsed._replace(query='&'.join(cleaned_params)).geturl()
    return parsed._replace(query='').geturl()


# ========== LRCFetcher (Embedded lyrics engine from lrc_fetcher.py) ==========
class LRCFetcher:
    """Robust lyrics fetcher using ffprobe for metadata extraction."""
    def __init__(self):
        self.session = requests.Session() if HAS_REQUESTS else None
        # Suppress SSL warnings when verify=False is used
        if HAS_REQUESTS:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        self.ffprobe_cmd = self._find_ffprobe()
        
    def _find_ffprobe(self):
        """Find ffprobe in PATH or common locations."""
        if shutil.which("ffprobe"):
            return "ffprobe"
        # Check Winget packages (same pattern as ffmpeg)
        local_appdata = os.environ.get("LOCALAPPDATA", "")
        if local_appdata:
            pattern = os.path.join(local_appdata, "Microsoft", "WinGet", "Packages", "**", "ffprobe.exe")
            matches = glob.glob(pattern, recursive=True)
            if matches:
                return matches[0]
        return None

    def get_metadata(self, filepath):
        """Extract Artist, Title, Album using ffprobe, fallback to filename."""
        meta = {"artist": None, "title": None, "album": None}
        
        # 1. Try ffprobe if available
        if self.ffprobe_cmd:
            try:
                cmd = [
                    self.ffprobe_cmd,
                    "-v", "quiet",
                    "-print_format", "json",
                    "-show_format",
                    filepath
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
                if result.returncode == 0:
                    import json
                    data = json.loads(result.stdout)
                    tags = data.get("format", {}).get("tags", {})
                    tags_lower = {k.lower(): v for k, v in tags.items()}
                    
                    meta["artist"] = tags_lower.get("artist") or tags_lower.get("album_artist")
                    meta["title"] = tags_lower.get("title")
                    meta["album"] = tags_lower.get("album")
            except Exception:
                pass

        # 2. Fallback: Filename parsing
        if not meta["artist"] or not meta["title"]:
            filename = os.path.splitext(os.path.basename(filepath))[0]
            # Remove leading track numbers (e.g., "01 " or "01. ")
            clean_name = re.sub(r'^\d+[\s\.\-_]+', '', filename)
            
            parts = clean_name.split(" - ")
            if len(parts) >= 2:
                if not meta["artist"]: 
                    meta["artist"] = parts[0].strip()
                if not meta["title"]: 
                    meta["title"] = " - ".join(parts[1:]).strip()
            else:
                if not meta["title"]: 
                    meta["title"] = clean_name.strip()
                
        return meta

    def _get_artist_candidates(self, artist_raw):
        """Generate a list of artist variants to try."""
        candidates = [artist_raw]
        if "," in artist_raw: 
            candidates.append(artist_raw.split(",")[0].strip())
        if " & " in artist_raw: 
            candidates.append(artist_raw.split(" & ")[0].strip())
        if " x " in artist_raw.lower(): 
            candidates.append(re.split(r" [xX] ", artist_raw)[0].strip())
        
        unique = []
        for c in candidates:
            if c and c not in unique: 
                unique.append(c)
        return unique

    def fetch_lrc(self, artist, title, album, save_path):
        """Fetch LRC from LRCLIB with fallback search strategies."""
        if not artist or not title:
            return False

        candidates = self._get_artist_candidates(artist)
        
        for i, try_artist in enumerate(candidates):
            # Retry logic for network errors
            max_retries = 3
            for retry in range(max_retries):
                try:
                    # Try exact match first
                    url_get = "https://lrclib.net/api/get"
                    params = {"artist_name": try_artist, "track_name": title}
                    if album:
                        params["album_name"] = album
                    
                    # Disable SSL verification to bypass certificate issues
                    resp = self.session.get(url_get, params=params, timeout=15, verify=False)
                    data = None
                    
                    if resp.status_code == 200:
                        data = resp.json()
                    elif resp.status_code == 404:
                        # Search fallback
                        url_search = "https://lrclib.net/api/search"
                        q = f"{try_artist} {title}"
                        resp_search = self.session.get(url_search, params={"q": q}, timeout=15, verify=False)
                        if resp_search.status_code == 200:
                            results = resp_search.json()
                            if results:
                                data = results[0]
                    
                    if data:
                        lrc_content = data.get("syncedLyrics", "") or data.get("plainLyrics", "")
                        
                        if lrc_content:
                            with open(save_path, "w", encoding="utf-8") as f:
                                f.write(lrc_content)
                            print(f"    {Colors.OKGREEN}✅ {os.path.basename(save_path)}{Colors.ENDC}")
                            return True
                    
                    # If we got a response but no lyrics, don't retry
                    break
                        
                except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as e:
                    if retry < max_retries - 1:
                        time.sleep(0.5)  # Brief pause before retry
                        continue
                    else:
                        if i == len(candidates) - 1:
                            print(f"    {Colors.WARNING}⚠️  Network error (try again later){Colors.ENDC}")
                        break
                except Exception as e:
                    if i == len(candidates) - 1:
                        print(f"    {Colors.WARNING}⚠️  Error: {str(e)[:50]}{Colors.ENDC}")
                    break
                
        return False

    def scan_folder(self, folder_path):
        """Scan folder for audio files and fetch lyrics."""
        folder = Path(folder_path)
        if not folder.exists():
            return

        extensions = ['*.mp3', '*.flac', '*.m4a', '*.wav', '*.ogg']
        files = []
        for ext in extensions:
            files.extend(list(folder.glob(ext)))
            
        if not files:
            return

        for filepath in files:
            # Check if lrc exists
            lrc_path = filepath.with_suffix(".lrc")
            if lrc_path.exists():
                continue
                
            meta = self.get_metadata(str(filepath))
            artist = meta["artist"]
            title = meta["title"]
            album = meta["album"]
            
            if not artist or not title:
                print(f"    {Colors.WARNING}⏭️  Skip: {filepath.name} (No metadata){Colors.ENDC}")
                continue
                
            print(f"    🔍 {artist} - {title}")
            self.fetch_lrc(artist, title, album, str(lrc_path))
            time.sleep(0.3)  # Rate limiting

class LibraryManager:
    def __init__(self, root_path):
        self.root = Path(root_path)
        self.library = self.scan_library()

    def scan_library(self):
        library = {}
        for artist_path in self.root.glob("*/"):
            if artist_path.name.lower() == "playlists":
                continue
            artist = artist_path.name
            library[artist] = {}
            for album_path in artist_path.glob("*/"):
                album = album_path.name
                tracks = (
                    list(album_path.glob("*.flac")) +
                    list(album_path.glob("*.mp3")) +
                    list(album_path.glob("*.m4a")) +
                    list(album_path.glob("*.ogg")) +
                    list(album_path.glob("*.wav"))
                )
                if tracks:
                    library[artist][album] = {
                        "path": str(album_path),
                        "track_count": len(tracks)
                    }
        return library

    def get_numbered_items(self):
        items = []
        i = 1
        for artist in sorted(self.library.keys()):
            for album in sorted(self.library[artist].keys()):
                items.append((i, artist, album))
                i += 1
        return items

    def get_album_path(self, artist, album):
        return self.library.get(artist, {}).get(album, {}).get("path")

class MusicDownloader:
    def __init__(self):
        self._check_ffmpeg()
        self.library = LibraryManager(DOWNLOAD_ROOT)
        self.mp3_mode = False  # Default: FLAC
        self.music_only = False # Default: Allow MVs
        self.lyrics_mode = True # Default: Download Lyrics

    def _check_ffmpeg(self):
        """Check if ffmpeg is available in PATH or local directory. Auto-find if possible."""
        # 1. Check PATH
        if shutil.which("ffmpeg"):
            return

        print(f"{Colors.WARNING}⚠️  ffmpeg not found in PATH. Searching common locations...{Colors.ENDC}")
        
        # 2. Search in Winget packages (recursive)
        local_appdata = os.environ.get("LOCALAPPDATA", "")
        if local_appdata:
            pattern = os.path.join(local_appdata, "Microsoft", "WinGet", "Packages", "**", "ffmpeg.exe")
            matches = glob.glob(pattern, recursive=True)
            if matches:
                 ffmpeg_path = matches[0]
                 ffmpeg_dir = os.path.dirname(ffmpeg_path)
                 
                 print(f"{Colors.OKGREEN}✅ Found ffmpeg: {ffmpeg_path}{Colors.ENDC}")
                 print(f"{Colors.OKCYAN}   Adding to temporary PATH...{Colors.ENDC}")
                 
                 # Add to PATH for this process
                 os.environ["PATH"] += os.pathsep + ffmpeg_dir
                 return

        # 3. Check local 'bin' folder or current directory (fallback)
        if hasattr(sys, 'frozen'):
             base_dir = os.path.dirname(sys.executable)
        else:
             base_dir = os.path.dirname(os.path.abspath(__file__))
             
        local_ffmpeg = os.path.join(base_dir, "ffmpeg.exe")
        if os.path.exists(local_ffmpeg):
             os.environ["PATH"] += os.pathsep + base_dir
             return

        # If we are here, it's truly missing
        print(f"{Colors.FAIL}❌ CRITICAL ERROR: ffmpeg not found!{Colors.ENDC}")
        print(f"{Colors.WARNING}This tool requires ffmpeg to process audio and covers.{Colors.ENDC}")
        input("Press Enter to continue anyway (or Ctrl+C to exit)...")


    # ---------- yt-dlp ----------
    def _yt_dlp_cmd(self, outtmpl, url, fmt="mp3"):
        # Base command builder (Shared)
        cmd = [
            YT_DLP_CMD,
            "--no-warnings",
            "--ignore-errors",
            "--extract-audio",
            "--write-info-json",  # Required for accurate lyrics
            "--add-metadata",
        ]

        if self.music_only:
            # Filter: must be a "track" (official audio usually has this)
            cmd.extend(["--match-filter", "track"])

        # Format specific
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
            url
        ])
        return cmd

    # ---------- cover postprocess ----------
    def _run(self, cmd):
        return subprocess.run(cmd, check=True)

    def _make_square_500(self, img_in, img_out):
        # NO BLACK BARS: crop center to square → scale to 500x500
        vf = "crop='min(iw,ih):(min(iw,ih))',scale=500:500"
        cmd = [FFMPEG_CMD, "-y", "-i", img_in, "-vf", vf, "-q:v", "1", img_out]
        self._run(cmd)

    def _embed_cover_into_flac(self, flac_path, cover_jpg_500):
        # Re-mux audio copy + attach picture
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
            tmp
        ]
        self._run(cmd)
        os.replace(tmp, flac_path)

    def _find_best_thumbnail_for_trackbase(self, base_no_ext):
        candidates = [
            base_no_ext + ".jpg",
            base_no_ext + ".webp",
            base_no_ext + ".png",
        ]
        for p in candidates:
            if os.path.exists(p):
                return p
        return None

    def _fix_all_covers(self, folder):
        """Fix covers for both FLAC and MP3 in the folder"""
        # Process FLAC
        flacs = sorted(glob.glob(os.path.join(folder, "*.flac")))
        if flacs:
            for flac in flacs:
                self._process_single_file_cover(flac)
        
        # Process MP3
        mp3s = sorted(glob.glob(os.path.join(folder, "*.mp3")))
        if mp3s:
            for mp3 in mp3s:
                self._process_single_file_cover(mp3)

    def _process_single_file_cover(self, filepath):
        base = os.path.splitext(filepath)[0]
        thumb = self._find_best_thumbnail_for_trackbase(base)
        if not thumb:
            return

        cover500 = base + ".cover500.jpg"
        try:
            self._make_square_500(thumb, cover500)
            self._embed_cover_into_flac(filepath, cover500)
            print(f"{Colors.OKGREEN}🖼️  Embedded 500x500 cover → {os.path.basename(filepath)}{Colors.ENDC}")
            
        except Exception as e:
            print(f"{Colors.FAIL}❌ Cover embed failed for {os.path.basename(filepath)}: {e}{Colors.ENDC}")
        finally:
            if os.path.exists(cover500):
                os.remove(cover500)
            for ext in (".jpg", ".webp", ".png"):
                p = base + ext
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except:
                        pass

    # ---------- lyrics & cleanup ----------
    def _post_process_downloads(self, folder, spinner):
        """Clean .info.json and run robust lyrics fetcher."""
        # 1. Cleanup Junk (Priority)
        jsons = glob.glob(os.path.join(folder, "*.info.json"))
        for json_path in jsons:
            try:
                os.remove(json_path)
            except Exception as e:
                print(f"  {Colors.FAIL}⚠️  Failed to cleanup {os.path.basename(json_path)}: {e}{Colors.ENDC}")

        # 2. Fetch Lyrics (if enabled)
        if self.lyrics_mode and HAS_REQUESTS:
            try:
                fetcher = LRCFetcher()
                spinner.stop(True)
                print(f"  {Colors.OKCYAN}🔍 Scanning for lyrics...{Colors.ENDC}")
                fetcher.scan_folder(folder)
                spinner.start("Finalizing...")
            except Exception as e:
                import traceback
                print(f"{Colors.FAIL}❌ Lyrics Engine Error: {e}{Colors.ENDC}")
                traceback.print_exc()

    def cleanup_junk(self):
        """Recursively delete .info.json files in DOWNLOAD_ROOT"""
        print(f"\n{Colors.WARNING}🧹 Scanning for junk files (.info.json)...{Colors.ENDC}")
        count = 0
        deleted_size = 0
        
        for root, dirs, files in os.walk(DOWNLOAD_ROOT):
            for file in files:
                if file.endswith(".info.json"):
                    path = os.path.join(root, file)
                    try:
                        size = os.path.getsize(path)
                        os.remove(path)
                        count += 1
                        deleted_size += size
                    except Exception as e:
                        print(f"  {Colors.FAIL}Failed to delete {file}: {e}{Colors.ENDC}")

        mb_saved = deleted_size / (1024 * 1024)
        print(f"{Colors.OKGREEN}✅ Cleanup Complete! Deleted {count} files ({mb_saved:.2f} MB freed).{Colors.ENDC}")

    # ---------- execution wrapper ----------
    def _run_download(self, folder, link, playlist_mode=False):
        os.makedirs(folder, exist_ok=True)
        link = clean_url(link)
        fmt = "MP3" if self.mp3_mode else "FLAC"
        filter_msg = " [Music Only]" if self.music_only else ""
        
        print(f"{Colors.OKGREEN}🎵 Downloading → {os.path.basename(folder)} ({fmt}{filter_msg}){Colors.ENDC}")
        print(f"{Colors.OKCYAN}🔗 {link}{Colors.ENDC}")

        # Template - ADDED SPACE after number
        outtmpl = os.path.join(folder, "%(playlist_index|00|)s %(title)s.%(ext)s")
        
        spinner = Spinner()
        spinner.start(f"yt-dlp processing...")

        cmd = self._yt_dlp_cmd(outtmpl, link, "mp3" if self.mp3_mode else "flac")
        
        try:
            result = subprocess.run(
                cmd, 
                stdout=subprocess.DEVNULL, 
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace' 
            )
            
            if result.returncode != 0:
                spinner.stop(False)
                
                # Check known "Skip" conditions
                err_lower = result.stderr.lower()
                if "does not match filter" in err_lower:
                    print(f"{Colors.WARNING}⏭️  Skipped (Not a music track/filter mismatch){Colors.ENDC}")
                    return True 
                elif "video unavailable" in err_lower:
                    print(f"{Colors.WARNING}⏭️  Skipped (Video Unavailable/Copyright Blocked){Colors.ENDC}")
                    # Don't return here, might be a playlist with other valid items
                else:
                    print(f"{Colors.FAIL}❌ yt-dlp warning/error (continuing processing...):{Colors.ENDC}")
                    print(result.stderr)
                    # Don't return False, try to process whatever was downloaded
            
            spinner.start("Fixing covers...") # Restart spinner if it was stopped
            self._fix_all_covers(folder)
            
            spinner.message = "Post-processing (Lyrics & Cleanup)..."
            self._post_process_downloads(folder, spinner)
            
            spinner.stop(True)
            return True

        except Exception as e:
            spinner.stop(False)
            print(f"{Colors.FAIL}❌ Error: {e}{Colors.ENDC}")
            # Try to save whatever we have
            try:
                print("Attempting to salvage downloaded files...")
                self._fix_all_covers(folder)
            except:
                pass
            return False

    def download_single_url(self, folder_name, url):
        full_path = os.path.join(DOWNLOAD_ROOT, folder_name)
        return self._run_download(full_path, url)

    def download_playlist_url(self, playlist_name, url):
        full_path = os.path.join(DOWNLOAD_ROOT, "Playlists", playlist_name)
        return self._run_download(full_path, url)

    # ---------- library display ----------
    def print_compact_library(self):
        items = self.library.get_numbered_items()
        total_tracks = sum(
            self.library.library[artist][album]["track_count"]
            for artist in self.library.library
            for album in self.library.library[artist]
        ) if self.library.library else 0

        print(f"\n{Colors.HEADER}📚 YOUR LIBRARY ({len(self.library.library)} artists, {total_tracks} tracks){Colors.ENDC}")
        print("=" * 70)

        if not items:
            print(f"{Colors.WARNING}  (Empty - add your first artist!){Colors.ENDC}")
            return

        for item_id, artist, album in items:
            track_count = self.library.library[artist][album]["track_count"]
            print(f"{Colors.OKCYAN}{item_id:2d}{Colors.ENDC}. 🎤 {Colors.OKBLUE}{artist:20}{Colors.ENDC} | "
                  f"📀 {Colors.WARNING}{album:<25}{Colors.ENDC} [{track_count} tracks]")

    # ---------- snowsky mode ----------
    def interactive_playlist_selector(self, playlist_name):
        items = self.library.get_numbered_items()
        if not items:
            print(f"{Colors.FAIL}❌ No library items!{Colors.ENDC}")
            return

        print(f"\n{Colors.OKGREEN}🎧 Snowsky playlist '{playlist_name}'{Colors.ENDC}")
        print(f"{Colors.OKCYAN}💡 Enter: 1,2,4 or 1-3 (Enter = done){Colors.ENDC}")
        self.print_compact_library()

        selected = []
        while True:
            choice = input(f"\n{Colors.OKCYAN}→ Items: {Colors.ENDC}").strip()
            if not choice:
                break
            try:
                if '-' in choice:
                    start, end = map(int, choice.split('-'))
                    for i in range(start, end + 1):
                        if 1 <= i <= len(items):
                            selected.append(items[i-1])
                else:
                    for num in map(int, choice.split(',')):
                        if 1 <= num <= len(items):
                            selected.append(items[num-1])
                print(f"{Colors.OKGREEN}✅ {len(selected)} items selected{Colors.ENDC}")
            except:
                print(f"{Colors.FAIL}❌ Invalid: {choice}{Colors.ENDC}")

        if selected:
            self.create_playlist_folders(playlist_name, selected)

    def create_playlist_folders(self, playlist_name, selected_items):
        playlist_root = os.path.join(DOWNLOAD_ROOT, "Playlists", playlist_name)
        os.makedirs(playlist_root, exist_ok=True)

        print(f"\n{Colors.OKGREEN}✅ Snowsky copies → Playlists/{playlist_name}/{Colors.ENDC}")
        for _, artist, album in selected_items:
            src = self.library.get_album_path(artist, album)
            if not src:
                continue
            dest_name = f"{artist} - {album}"
            dest = os.path.join(playlist_root, dest_name)

            if os.path.exists(dest):
                print(f"  {Colors.WARNING}⏭️  Exists: {dest_name}{Colors.ENDC}")
            else:
                shutil.copytree(src, dest)
                print(f"  {Colors.OKGREEN}✅ Copied: {dest_name}{Colors.ENDC}")

        print(f"{Colors.OKGREEN}🎉 Ready!{Colors.ENDC}")

def main():
    print(f"{Colors.HEADER}🎵 SNOWSKY RETRO MINI MUSIC MANAGER v16.2 (Cleanup Fixed){Colors.ENDC}")
    print(f"{Colors.OKCYAN}📁 {DOWNLOAD_ROOT} (FLAC + 500x500 JPG embedded covers){Colors.ENDC}")
    print("=" * 70)

    downloader = MusicDownloader()

    while True:
        downloader.print_compact_library()

        mode_str = f"{Colors.FAIL}MP3{Colors.ENDC}" if downloader.mp3_mode else f"{Colors.OKGREEN}FLAC{Colors.ENDC}"
        filter_str = f"{Colors.OKGREEN}ON{Colors.ENDC}" if downloader.music_only else f"{Colors.FAIL}OFF{Colors.ENDC}"
        
        print(f"\n{Colors.BOLD}🎛️  SNOWSKY MODES [Format: {mode_str}] [Music Only: {filter_str}]{Colors.ENDC}")
        print("  1) ➕ Any URL → Artist/Album folder")
        print("  2) 📥 Playlist URL → Playlists/Name/")
        print("  3) 🎧 Snowsky playlist from library (copy albums)")
        print("  4) 📦 Batch Artist Download (Multiple URLs)")
        print("  9) 🧹 Clean up junk files (.info.json)")
        print("  m) 🔄 Toggle MP3/FLAC Mode")
        print(f"  f) 🎵 Toggle Music Only Filter (Skip MVs)")
        print(f"  l) 🎤 Toggle Lyrics Download [{Colors.OKGREEN if downloader.lyrics_mode else Colors.FAIL}{'ON' if downloader.lyrics_mode else 'OFF'}{Colors.ENDC}]")
        print("  0) 🚪 Quit")

        try:
            choice = input(f"\n{Colors.OKCYAN}Choice: {Colors.ENDC}").strip()

            if choice == "1":
                folder_name = input("📁 Folder name (Artist/Album): ").strip()
                link = input("🔗 YouTube/YT Music URL: ").strip()
                if folder_name and link:
                    downloader.download_single_url(folder_name, link)
                    downloader.library = LibraryManager(DOWNLOAD_ROOT)

            elif choice == "2":
                playlist_name = input("📀 Playlist name: ").strip()
                link = input("🔗 YouTube/YT Music playlist URL: ").strip()
                if playlist_name and link:
                    downloader.download_playlist_url(playlist_name, link)
                    downloader.library = LibraryManager(DOWNLOAD_ROOT)
            
            elif choice == "3":
                playlist_name = input("🎧 Snowsky playlist: ").strip()
                if playlist_name:
                    downloader.interactive_playlist_selector(playlist_name)
                    downloader.library = LibraryManager(DOWNLOAD_ROOT)

            elif choice == "4":
                artist_name = input("🎤 Artist Name (Folder will be Artist/Album): ").strip()
                if artist_name:
                    print(f"{Colors.OKCYAN}Paste album URLs. Input 'Album Name' then 'URL'.")
                    print(f"Type 'GO' when finished adding to queue.{Colors.ENDC}")
                    
                    queue = []
                    while True:
                        print(f"\n{Colors.BOLD}--- Item {len(queue) + 1} ---{Colors.ENDC}")
                        alb = input("💿 Album Name (or 'GO' to start): ").strip()
                        if alb.upper() == "GO":
                            break
                        if not alb:
                            continue
                            
                        lnk = input("🔗 URL: ").strip()
                        if not lnk:
                            continue
                            
                        queue.append((alb, lnk))
                    
                    if queue:
                        print(f"\n{Colors.OKGREEN}🚀 Starting Batch Download for {artist_name} ({len(queue)} items)...{Colors.ENDC}")
                        success_count = 0
                        
                        for album_name, link in queue:
                            # Construct proper folder path: Artist/Album
                            folder_path = os.path.join(artist_name, album_name)
                            print(f"\n{Colors.HEADER}>>> Downloading: {album_name}{Colors.ENDC}")
                            if downloader.download_single_url(folder_path, link):
                                success_count += 1
                        
                        print(f"\n{Colors.OKGREEN}✅ Batch Complete: {success_count}/{len(queue)} success.{Colors.ENDC}")
                        downloader.library = LibraryManager(DOWNLOAD_ROOT)

            elif choice == "9" or choice.lower() == "c":
                 downloader.cleanup_junk()

            elif choice.lower() == "m":
                downloader.mp3_mode = not downloader.mp3_mode
                print(f"{Colors.OKGREEN}🔄 Mode switched.{Colors.ENDC}")

            elif choice.lower() == "f":
                downloader.music_only = not downloader.music_only
                print(f"{Colors.OKGREEN}🎵 Filter switched.{Colors.ENDC}")

            elif choice.lower() == "l":
                downloader.lyrics_mode = not downloader.lyrics_mode
                print(f"{Colors.OKGREEN}🎤 Lyrics mode switched.{Colors.ENDC}")

            elif choice == "0":
                break

            if choice != "4": 
                input(f"\n{Colors.OKBLUE}⏸️  Press Enter...{Colors.ENDC}")

        except KeyboardInterrupt:
            print(f"\n{Colors.WARNING}⚠️  Interrupted by user.{Colors.ENDC}")
            break
        except Exception as e:
            print(f"\n{Colors.FAIL}❌ Unexpected Error: {e}{Colors.ENDC}")
            input("Press Enter to continue...")

    print(f"\n{Colors.OKGREEN}🎉 Snowsky ready!{Colors.ENDC}")

if __name__ == "__main__":
    main()
