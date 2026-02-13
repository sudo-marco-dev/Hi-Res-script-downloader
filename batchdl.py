import os
import subprocess
import sys
import time
import threading
from pathlib import Path

# Force UTF-8 for Windows Console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass # Python < 3.7

from urllib.parse import urlparse
import shutil
import glob
import re
import concurrent.futures
import json
import logging

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# ========== DEPENDENCY CHECK ==========
try:
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn, ProgressColumn
    from rich.panel import Panel
    from rich.table import Table
    from rich.tree import Tree
    from rich.text import Text
    from rich import print as rprint
    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    print("⚠️  'rich' library not found. Installing is recommended for best experience.")
    print("   Run: pip install rich")
    # We will fallback to basic print where possible or exit if critical

# ========== CUSTOM PROGRESS COLUMN ==========
if HAS_RICH:
    class InfoColumn(ProgressColumn):
        """Custom column to display download speed and ETA from yt-dlp."""
        
        def render(self, task):
            """Render speed and ETA info."""
            speed = task.fields.get("speed", "")
            eta = task.fields.get("eta", "")
            
            if speed and eta:
                return Text(f"{speed} • ETA {eta}", style="dim cyan")
            elif speed:
                return Text(speed, style="dim cyan")
            elif eta:
                return Text(f"ETA {eta}", style="dim cyan")
            else:
                return Text("", style="dim cyan")


# ========== LOGGING SETUP ==========
logging.basicConfig(
    filename='batchdl.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# ========== CONFIG MANAGER ==========
DEFAULT_CONFIG = {
    "music_folder": os.path.join(os.path.expanduser("~"), "Music", "batchdl"),
    "mp3_mode": False,
    "music_only": False,
    "lyrics_mode": True,
    "cookies_browser": None,  # e.g. "firefox", "chrome"
    "max_workers": 2,
    "parallel_mode": True,
    "filename_template": "%(playlist_index|00|)s %(title)s.%(ext)s"
}

class ConfigManager:
    def __init__(self):
        self.config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        self.config = self.load_config()

    def load_config(self):
        if not os.path.exists(self.config_path):
            return self.first_run_wizard()
        
        try:
            with open(self.config_path, 'r') as f:
                user_config = json.load(f)
                # Merge with defaults to ensure all keys exist
                config = DEFAULT_CONFIG.copy()
                config.update(user_config)
                return config
        except Exception as e:
            print(f"❌ Error loading config: {e}")
            logging.error(f"Config load failed: {e}")
            return DEFAULT_CONFIG.copy()

    def save_config(self):
        try:
            with open(self.config_path, 'w') as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            logging.error(f"Config save failed: {e}")

    def first_run_wizard(self):
        print("\n⚙️  FIRST RUN SETUP")
        print("   It looks like you don't have a config file yet.")
        
        # Ask for music folder
        default_root = DEFAULT_CONFIG["music_folder"]
        print(f"   Default Music Folder: {default_root}")
        choice = input(f"   Press Enter to accept or type new path: ").strip()
        
        new_config = DEFAULT_CONFIG.copy()
        if choice:
            new_config["music_folder"] = os.path.abspath(choice)
        
        # Create folder if it doesn't exist
        os.makedirs(new_config["music_folder"], exist_ok=True)
        
        # Save
        try:
            with open(self.config_path, 'w') as f:
                json.dump(new_config, f, indent=4)
            print("✅ Config saved!")
        except Exception as e:
            print(f"❌ Could not save config: {e}")
            
        return new_config

# Initialize Global State
CONF_MANAGER = ConfigManager()
CONFIG = CONF_MANAGER.config
DOWNLOAD_ROOT = CONFIG["music_folder"]

def find_yt_dlp():
    # 1. Check in the same directory as the python executable (Scripts/ or bin/)
    # This helps when running from a venv without activation
    if sys.platform == "win32":
        candidate = os.path.join(os.path.dirname(sys.executable), "yt-dlp.exe")
        if os.path.exists(candidate):
            return candidate
        # Also check Scripts if we are in the root of venv? 
        # Usually sys.executable IS in Scripts on Windows venv.
    else:
        candidate = os.path.join(os.path.dirname(sys.executable), "yt-dlp")
        if os.path.exists(candidate):
            return candidate

    # 2. Check in script directory (portable usage)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if sys.platform == "win32":
        local_exe = os.path.join(script_dir, "yt-dlp.exe")
    else:
        local_exe = os.path.join(script_dir, "yt-dlp")
    
    if os.path.exists(local_exe):
        return local_exe
        
    # 3. Fallback to PATH
    import shutil
    if shutil.which("yt-dlp"):
         return "yt-dlp"
         
    return "yt-dlp" # Hope for the best

    return "yt-dlp" # Hope for the best

YT_DLP_CMD = find_yt_dlp()
FFMPEG_CMD = "ffmpeg"

def _check_node_js():
    """Ensure Node.js is in PATH for yt-dlp."""
    if shutil.which("node"):
        return

    # Common Windows install locations
    common_paths = [
        os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "nodejs"),
        os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), "nodejs"),
    ]
    
    for p in common_paths:
        node_exe = os.path.join(p, "node.exe")
        if os.path.exists(node_exe):
            print(f"✅ Found Node.js: {node_exe}")
            print(f"   Adding to PATH...")
            os.environ["PATH"] += os.pathsep + p
            return

    print(f"⚠️  Node.js not found in PATH or common locations.")
    print(f"   yt-dlp requires Node.js for signature solving.")

_check_node_js()

# ========== UI & SPINNER ==========
class Spinner:
    """Wrapper that uses Rich Progress if available, else classic text spinner."""
    def __init__(self):
        self.rich_progress = None
        self.task_id = None
        self.classic_thread = None
        self.classic_spinning = False
        self.message = ""

    def start(self, message):
        self.message = message
        if HAS_RICH:
            if self.rich_progress:
                self.update(message)
                return

            # Create a transient progress bar just for spinner
            self.rich_progress = Progress(
                SpinnerColumn(spinner_name="dots"),
                TextColumn("[bold cyan]{task.description}"),
                transient=True
            )
            self.task_id = self.rich_progress.add_task(message, total=None)
            self.rich_progress.start()
        else:
            if self.classic_spinning:
                 self.message = message
                 return

            # Fallback
            self.classic_spinning = True
            self.classic_thread = threading.Thread(target=self._spin_classic, daemon=True)
            self.classic_thread.start()

    def update(self, message):
        self.message = message
        if HAS_RICH and self.rich_progress and self.task_id is not None:
            self.rich_progress.update(self.task_id, description=message)
        
    def _spin_classic(self):
        chars = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
        i = 0
        while self.classic_spinning:
            sys.stdout.write(f'\r{Colors.OKGREEN}{chars[i % len(chars)]}{Colors.ENDC} {self.message}')
            sys.stdout.flush()
            i += 1
            time.sleep(0.1)

    def stop(self, success=True):
        if HAS_RICH and self.rich_progress:
            self.rich_progress.stop()
            self.rich_progress = None
            self.task_id = None
            symbol = "[bold green]✅ COMPLETE[/bold green]" if success else "[bold red]❌ FAILED[/bold red]"
            rprint(f"{symbol} {self.message}")
        elif self.classic_spinning:
            self.classic_spinning = False
            if self.classic_thread:
                self.classic_thread.join()
                self.classic_thread = None
            status = f"{Colors.OKGREEN}✅ COMPLETE{Colors.ENDC}" if success else f"{Colors.FAIL}❌ FAILED{Colors.ENDC}"
            print(f'\r{status:>20} {self.message}')

class SnowskyUI:
    """Rich TUI Manager"""
    def __init__(self):
        self.console = Console() if HAS_RICH else None

    def print_header(self):
        if HAS_RICH:
            self.console.clear()
            title = Text(" SNOWSKY RETRO MINI MANAGER v17.1 ", style="bold white on blue", justify="center")
            
            # Info Panel
            info = f"[dim]Folder:[/dim] [yellow]{DOWNLOAD_ROOT}[/yellow]\n"
            info += f"[dim]Config:[/dim] [cyan]{CONF_MANAGER.config_path}[/cyan]"
            
            self.console.print(Panel(info, title=title, border_style="blue"))
        else:
            print(f"{Colors.HEADER}🎵 SNOWSKY RETRO MINI MUSIC MANAGER v17.1{Colors.ENDC}")
            print(f"{Colors.OKCYAN}📁 {DOWNLOAD_ROOT}{Colors.ENDC}")
            print("=" * 70)

    def print_menu(self, dl_manager):
        # Read current state from config/manager
        mp3 = CONFIG.get("mp3_mode", False)
        music_filter = CONFIG.get("music_only", False)
        lyrics = CONFIG.get("lyrics_mode", True)
        parallel = CONFIG.get("parallel_mode", True)

        if HAS_RICH:
            # Status Flags
            fmt_style = "[bold red]MP3[/]" if mp3 else "[bold green]FLAC[/]"
            filter_style = "[green]ON[/]" if music_filter else "[dim]OFF[/]"
            lyrics_style = "[green]ON[/]" if lyrics else "[dim]OFF[/]"
            parallel_style = "[bold green]PARALLEL[/]" if parallel else "[bold yellow]SINGLE[/]"

            table = Table(show_header=False, box=None, padding=(0, 2))
            table.add_column("Key", style="bold cyan", justify="right")
            table.add_column("Action")
            
            table.add_row("1", "➕  Any URL → Artist/Album")
            table.add_row("2", "📥  Playlist URL → Playlists/")
            table.add_row("3", "🎧  Snowsky Playlist (Copy Library)")
            table.add_row("4", "📦  Batch Artist (Multiple URLs)")
            table.add_row("", "")
            table.add_row("v", "📚  View Library (Tree)")
            table.add_row("c", "🧹  Clean Junk Files")
            table.add_row("", "")
            table.add_row("m", f"🔄  Toggle Format ({fmt_style})")
            table.add_row("f", f"🎵  Music Only Filter ({filter_style})")
            table.add_row("l", f"🎤  Lyrics Download ({lyrics_style})")
            table.add_row("p", f"⚡  Download Mode ({parallel_style})")
            table.add_row("0", "🚪  Quit")

            panel = Panel(
                table, 
                title="[bold]Main Menu[/bold]", 
                border_style="green",
                subtitle="[dim]Select an option...[/dim]"
            )
            self.console.print(panel)
        else:
            # Fallback Menu
            print("\n1) URL -> Artist/Album")
            print("2) Playlist -> Playlists/")
            print("3) Snowsky Copy")
            print("v) View Library")
            print("0) Quit")


    def show_library_tree(self, library_path):
        if not HAS_RICH:
            print("Tree view requires 'rich'.")
            return

        tree = Tree(f"📁 [bold yellow]{os.path.basename(library_path)}[/]")
        
        # Walk logic optimized for display
        # We only want top level artists and their albums
        try:
            # Get Artists
            artists = sorted([d for d in os.listdir(library_path) if os.path.isdir(os.path.join(library_path, d))])
            
            for artist in artists:
                if artist == "Playlists":
                    style = "bold magenta"
                else:
                    style = "bold blue"
                    
                artist_node = tree.add(f"[{style}]{artist}[/]")
                artist_path = os.path.join(library_path, artist)
                
                # Get Albums/Subfolders
                albums = sorted([d for d in os.listdir(artist_path) if os.path.isdir(os.path.join(artist_path, d))])
                for album in albums:
                    album_path = os.path.join(artist_path, album)
                    # Count files
                    track_count = len([f for f in os.listdir(album_path) if f.lower().endswith(('.mp3', '.flac', '.m4a'))])
                    artist_node.add(f"💿 [green]{album}[/] [dim]({track_count})[/]")
                    
        except Exception as e:
            tree.add(f"[red]Error scanning library: {e}[/]")

        self.console.print(tree)
        input("\nPress Enter to return...")

# Legacy Colors needed for MusicDownloader internal prints if not fully refactored yet
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def safe_file_op(func, *args, retries=3, delay=0.5, **kwargs):
    """Gracefully handle WinError 32 (file in use) with retries."""
    for i in range(retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if i == retries - 1:
                logging.warning(f"File op failed after {retries} attempts: {e}")
                raise
            time.sleep(delay)
    return None

def clean_url(url: str) -> str:
    """Clean URL by removing tracking parameters while preserving video/playlist IDs."""
    parsed = urlparse(url.strip())
    if not parsed.query:
        return url.strip()
    
    # Parameters to KEEP: v (video), list (playlist), index (track position)
    keep = {'v', 'list', 'index'}
    
    # Use parse_qs for robust parsing
    from urllib.parse import parse_qs, urlencode
    qs = parse_qs(parsed.query)
    filtered = {k: v for k, v in qs.items() if k in keep}
    
    if not filtered:
        # If no essential params, strip tracking entirely for YouTube
        if 'youtube' in parsed.netloc or 'youtu.be' in parsed.netloc:
             return parsed._replace(query='').geturl()
        return url.strip()

    return parsed._replace(query=urlencode(filtered, doseq=True)).geturl()


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
    """Manages library scanning (Recursive + Caching)."""
    def __init__(self, root_path):
        self.root = Path(root_path)
        self.items = [] # Linear list for selection [(Artist, Album, Path, TrackDate)]
        self.refresh_library()

    def refresh_library(self):
        self.items = []
        if not self.root.exists():
            return

        # Recursive scan, but we want to group by Folder (Album)
        # Strategy: Walk all folders. if folder contains audio, it's an album.
        # "Artist" is the parent folder name.
        audio_exts = {'.mp3', '.flac', '.m4a', '.wav', '.ogg'}
        
        for root, dirs, files in os.walk(self.root):
            # Skip Playlists folder from being treated as an Artist/Album source
            # But we might want to allow copying FROM playlists?
            # User said: "Inbox Playlists folder" -> Index it? user said Yes.
            # But usually we copy TO playlists. If we copy FROM playlists, we treat them as source.
            
            # Let's keep it simple: Treat any folder with audio as an "Album".
            # The "Artist" is the parent folder.
            
            path_obj = Path(root)
            has_audio = any(f.lower().endswith(tuple(audio_exts)) for f in files)
            
            if has_audio:
                album_name = path_obj.name
                parent_name = path_obj.parent.name
                
                # If root is the library root, parent is meaningless?
                if path_obj == self.root:
                    continue
                    
                # Fix for "Playlists" folder itself if it has tracks
                if parent_name == "Playlists":
                    artist_name = "Playlist"
                elif path_obj.parent == self.root:
                     # This is Artist folder directly containing songs (loose files)
                     artist_name = album_name # Use current folder as artist? 
                     # Wait, if loose files in Artist folder: Artist/song.mp3
                     # Then roots is Artist.
                     artist_name = album_name
                     album_name = "Singles"
                else:
                    artist_name = parent_name

                # Count tracks
                track_count = sum(1 for f in files if f.lower().endswith(tuple(audio_exts)))
                
                self.items.append({
                    "artist": artist_name,
                    "album": album_name,
                    "path": str(path_obj),
                    "tracks": track_count
                })

        # Sort by Artist then Album
        self.items.sort(key=lambda x: (x["artist"].lower(), x["album"].lower()))

    def get_numbered_items(self):
        """Returns list of (index, artist, album, path) for selection"""
        return [(i+1, item["artist"], item["album"], item["path"]) for i, item in enumerate(self.items)]

    def get_album_path(self, artist, album):
        # Scan items to find match
        for item in self.items:
            if item["artist"] == artist and item["album"] == album:
                return item["path"]
        return None


class MusicDownloader:
    def __init__(self):
        self._check_ffmpeg()
        self.library = LibraryManager(DOWNLOAD_ROOT)
        self.mp3_mode = CONFIG.get("mp3_mode", False)
        self.music_only = CONFIG.get("music_only", False)
        self.lyrics_mode = CONFIG.get("lyrics_mode", True)

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
    def _find_cookies_file(self):
        """Auto-detect cookies.txt next to the script."""
        script_dir = os.path.dirname(os.path.abspath(__file__))
        cookies_path = os.path.join(script_dir, "cookies.txt")
        if os.path.exists(cookies_path):
            return cookies_path
        return None

    def _yt_dlp_cmd(self, outtmpl, url, fmt="mp3"):
        # Base command builder (Shared)
        cmd = [
            YT_DLP_CMD,
            "--no-warnings",
            "--ignore-errors",
            "--no-cache-dir",      # Help avoid some 403/throttling issues
            "--extract-audio",
            "--write-info-json",   # Required for accurate lyrics
            "--add-metadata",
            "--windows-filenames", # Ensure compatible filenames
            "--js-runtimes", "node",  # Use Node.js for YouTube JS signature solving
        ]
        
        # Cookie Config: cookies.txt file > cookies_browser config
        cookies_file = self._find_cookies_file()
        if cookies_file:
            cmd.extend(["--cookies", cookies_file])
        elif CONFIG.get("cookies_browser"):
            cmd.extend(["--cookies-from-browser", CONFIG["cookies_browser"]])

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
        # Suppress ffmpeg output unless error
        return subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

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
        safe_file_op(os.replace, tmp, flac_path)

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

    def _find_fallback_cover(self, folder):
        """Look for folder.jpg, cover.jpg, or any jpg in the folder."""
        candidates = ["folder.jpg", "cover.jpg", "front.jpg", "album.jpg"]
        for c in candidates:
            p = os.path.join(folder, c)
            if os.path.exists(p):
                return p
        
        # Last resort: Any larger JPG? (Risk of picking back cover)
        # safe to skip for now to avoid bad matches
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
        folder = os.path.dirname(filepath)
        
        thumb = self._find_best_thumbnail_for_trackbase(base)
        if not thumb:
            thumb = self._find_fallback_cover(folder)
            
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
                safe_file_op(os.remove, cover500)
            for ext in (".jpg", ".webp", ".png"):
                p = base + ext
                if os.path.exists(p):
                    try:
                        safe_file_op(os.remove, p)
                    except:
                        pass

    # ---------- lyrics & cleanup ----------
    def _post_process_downloads(self, folder, spinner=None, quiet=False):
        """Clean .info.json and run robust lyrics fetcher."""
        # 1. Cleanup Junk (Priority)
        jsons = glob.glob(os.path.join(folder, "*.info.json"))
        for json_path in jsons:
            try:
                safe_file_op(os.remove, json_path)
            except Exception:
                pass

        # 2. Fetch Lyrics (if enabled)
        if self.lyrics_mode and HAS_REQUESTS:
            try:
                # If we are in quiet mode (parallel), we shouldn't print extensive logs
                # But fetch_lrc prints too. 
                # Ideally, lrc fetcher should be quiet.
                fetcher = LRCFetcher()
                if spinner: spinner.start("Finalizing (Lyrics)...")
                fetcher.scan_folder(folder) # This prints to stdout... need to silence it or accept it.
                # For now, let it run.
            except Exception as e:
                logging.error(f"Lyrics Error: {e}")

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
    def _run_download(self, folder, link, playlist_mode=False, quiet=False, progress=None, task_id=None):
        os.makedirs(folder, exist_ok=True)
        link = clean_url(link)
        fmt = "MP3" if self.mp3_mode else "FLAC"
        filter_msg = " [Music Only]" if self.music_only else ""
        
        msg = f"Downloading → {os.path.basename(folder)} ({fmt})"
        if not quiet:
            print(f"{Colors.OKGREEN}🎵 {msg}{Colors.ENDC}")
            print(f"{Colors.OKCYAN}🔗 {link}{Colors.ENDC}")
            spinner = Spinner()
            spinner.start(f"yt-dlp processing...")
        elif progress and task_id:
            progress.update(task_id, description=f"⬇️ {os.path.basename(folder)} (yt-dlp)")

        # Template from Config
        tmpl_str = CONFIG.get("filename_template", "%(playlist_index|00|)s %(title)s.%(ext)s")
        outtmpl = os.path.join(folder, tmpl_str)
        
        # yt-dlp handles its own resumes. Bulk deleting .part files in parallel mode
        # causes threads to kill each other's downloads. 
        # Removed unsafe cleanup loop.

        cmd = self._yt_dlp_cmd(outtmpl, link, "mp3" if self.mp3_mode else "flac")
        
        # We need to capture stdout line by line for progress
        # And stderr for errors.
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, # Merge stderr into stdout to prevent pipe deadlock
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1 # Line buffered
            )

            # Regex for progress: [download]  45.0% of   3.45MiB at    2.00MiB/s ETA 00:01
            # Enhanced pattern to capture: percent, size, speed, ETA
            progress_pattern = re.compile(
                r'\[download\]\s+(\d+\.?\d*)%\s+of\s+~?(\S+)\s+at\s+(\S+)\s+ETA\s+(\S+)'
            )
            # Fallback pattern for just percentage (when other fields aren't available)
            simple_pattern = re.compile(r'\[download\]\s+(\d+\.?\d*)%')
            
            # Read stdout dynamically
            full_output = []
            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                
                if line:
                    full_output.append(line)
                    line_clean = line.strip()
                    # Check for detailed progress first
                    try:
                        match = progress_pattern.search(line_clean)
                        if match:
                            percent = float(match.group(1))
                            size = match.group(2)
                            speed = match.group(3)
                            eta = match.group(4)
                            
                            # Update progress with all fields
                            if progress and task_id:
                                progress.update(
                                    task_id, 
                                    completed=percent,
                                    description=f"⬇️ {os.path.basename(folder)}",
                                    speed=speed,
                                    eta=eta
                                )
                        else:
                            # Try simple pattern as fallback
                            simple_match = simple_pattern.search(line_clean)
                            if simple_match:
                                percent = float(simple_match.group(1))
                                if progress and task_id:
                                    progress.update(
                                        task_id, 
                                        completed=percent,
                                        description=f"⬇️ {os.path.basename(folder)}"
                                    )
                    except (ValueError, IndexError):
                        # Regex parsing failed, continue without crashing
                        pass
                    
                    # Also check for "Destination: ..." to identify current file?
                    # Keep it simple for now.

            # stdout, _ = process.communicate() # get remaining
            stdout = "".join(full_output)
            
            if process.returncode != 0:
                if not quiet: spinner.stop(False)
                
                # Combined output is in stdout now
                out_lower = stdout.lower() if stdout else ""
                
                # Check if some files were still produced despite errors (common in playlists)
                produced_files = any(f.endswith('.flac') or f.endswith('.mp3') for f in os.listdir(folder))
                
                if "does not match filter" in out_lower:
                    if not quiet: print(f"{Colors.WARNING}⏭️  Skipped (Not a music track/filter mismatch){Colors.ENDC}")
                    # Don't return yet, might have other files in playlist
                elif "video unavailable" in out_lower or "403" in out_lower:
                    if not quiet: print(f"{Colors.WARNING}⏭️  Skipped (Unavailable/Forbidden - Check Cookies){Colors.ENDC}")
                else:
                    if not quiet: 
                        print(f"{Colors.FAIL}❌ yt-dlp warning/error:{Colors.ENDC}")
                        print(stdout)
                    logging.error(f"yt-dlp error for {link}: {stdout}")
                
                # If nothing was downloaded at all and it's a hard error, return
                if not produced_files:
                    return False

            if not quiet: spinner.start("Fixing covers...") 
            elif progress and task_id: progress.update(task_id, description=f"🖼️ Covers: {os.path.basename(folder)}")
            
            # Stop spinner temporarily if we expect output from fix_covers
            # But fix_covers logic prints. 
            # Ideally we silence fix_covers or let it print above the spinner.
            # With transient=True, spinner disappears, print happens, spinner reappears (if updated).
            # But start() uses update() now, so it won't disappear if already running.
            
            self._fix_all_covers(folder)
            
            if not quiet: spinner.update("Post-processing (Lyrics & Cleanup)...")
            
            self._post_process_downloads(folder, spinner if not quiet else None, quiet=quiet)
            
            if not quiet: spinner.stop(True)
            return True

        except Exception as e:
            if not quiet: spinner.stop(False)
            print(f"{Colors.FAIL}❌ Error: {e}{Colors.ENDC}")
            logging.error(f"Download Exception {link}: {e}")
            return False

    def download_queue_parallel(self, queue_items):
        """
        queue_items: list of (folder_path, url)
        """
        if not queue_items: return

        parallel = CONFIG.get("parallel_mode", True)
        workers = CONFIG["max_workers"] if parallel else 1
        mode_str = "Parallel" if parallel else "Single-Threaded"
        
        print(f"\n🚀 Starting Batch ({len(queue_items)} items) | Mode: {mode_str} | Threads: {workers}")
        
        start_time = time.time()
        
        if HAS_RICH:
            with Progress(
                SpinnerColumn(),
                TextColumn("[bold cyan]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                InfoColumn(),
                transient=False
            ) as progress:
                
                task_overall = progress.add_task("[green]Total Batch Progress", total=len(queue_items))
                
                with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                    futures = []
                    for folder, url in queue_items:
                        future = executor.submit(self._parallel_worker, folder, url, progress)
                        futures.append(future)
                        # Stagger start only in parallel mode
                        if parallel:
                            time.sleep(2.0)

                    success_count = 0
                    fail_count = 0
                    failed_items = []

                    for future in concurrent.futures.as_completed(futures):
                        try:
                            if future.result():
                                success_count += 1
                            else:
                                fail_count += 1
                        except Exception as e:
                            logging.error(f"Worker failed: {e}")
                            fail_count += 1
                        progress.update(task_overall, advance=1)
            
            elapsed = time.time() - start_time
            
            # Summary Table
            if HAS_RICH:
                table = Table(title="Batch Summary", border_style="green" if fail_count == 0 else "red")
                table.add_column("Metric", style="bold")
                table.add_column("Value", justify="right")
                
                table.add_row("Total Time", f"{elapsed:.2f}s")
                table.add_row("Mode", mode_str)
                table.add_row("[green]Success[/]", str(success_count))
                table.add_row("[red]Failed[/]", str(fail_count))
                
                if fail_count > 0:
                     table.add_row("[yellow]Note[/]", "Check batchdl.log for details")

                Console().print(table)
            else:
                print(f"Batch Done: {success_count} OK, {fail_count} Failed. Time: {elapsed:.2f}s")
        else:
            # Fallback
            for i, (folder, url) in enumerate(queue_items):
                print(f"--- Item {i+1}/{len(queue_items)} ---")
                self._run_download(folder, url)

    def _parallel_worker(self, folder, url, progress):
        task_id = progress.add_task(f"⏳ Waiting: {os.path.basename(folder)}", total=100, speed="", eta="")
        try:
            result = self._run_download(folder, url, quiet=True, progress=progress, task_id=task_id)
            return result
        finally:
            progress.remove_task(task_id)

    def download_single_url(self, folder_name, url):
        full_path = os.path.join(DOWNLOAD_ROOT, folder_name)
        
        if HAS_RICH:
            with Progress(
                SpinnerColumn(),
                TextColumn("[bold cyan]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                InfoColumn(),
                transient=False
            ) as progress:
                task_id = progress.add_task(f"⬇️ {folder_name}", total=100, speed="", eta="")
                return self._run_download(full_path, url, quiet=True, progress=progress, task_id=task_id)
        else:
            return self._run_download(full_path, url)

    def download_playlist_url(self, playlist_name, url):
        full_path = os.path.join(DOWNLOAD_ROOT, "Playlists", playlist_name)
        
        if HAS_RICH:
            with Progress(
                SpinnerColumn(),
                TextColumn("[bold cyan]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                InfoColumn(),
                transient=False
            ) as progress:
                task_id = progress.add_task(f"⬇️ {playlist_name}", total=100, speed="", eta="")
                return self._run_download(full_path, url, quiet=True, progress=progress, task_id=task_id)
        else:
            return self._run_download(full_path, url)

    # ---------- library display ----------
    # ---------- library display ----------
    def print_compact_library(self):
        items = self.library.get_numbered_items()
        
        if HAS_RICH and self.library.items:
             # Use Rich Table for Snowsky Selector
             table = Table(title="Select Items to Copy", show_header=True, header_style="bold magenta")
             table.add_column("#", style="dim", width=4)
             table.add_column("Artist", style="cyan")
             table.add_column("Album", style="yellow")
             table.add_column("Tracks", justify="right")
             
             for i, artist, album, path in items:
                 # Find track count from underlying item
                 # items gives (i, artist, album, path)
                 # We need the track count from self.library.items
                 # But self.library.items is 0-indexed, so i-1
                 # Wait, items is [(1, ...), (2, ...)]
                 idx = i - 1
                 if 0 <= idx < len(self.library.items):
                     count = self.library.items[idx]["tracks"]
                     table.add_row(str(i), artist, album, str(count))
             
             # Create a console just for this or use global if available
             Console().print(table)
             return

        # Fallback Text
        print(f"\n{Colors.HEADER}📚 YOUR LIBRARY ({len(items)} albums){Colors.ENDC}")
        print("=" * 70)

        if not items:
            print(f"{Colors.WARNING}  (Empty - add your first artist!){Colors.ENDC}")
            return

        for i, artist, album, path in items:
            # We need track count again...
            count = "?"
            if 0 <= (i-1) < len(self.library.items):
                count = self.library.items[i-1]["tracks"]
                
            print(f"{Colors.OKCYAN}{i:2d}{Colors.ENDC}. 🎤 {Colors.OKBLUE}{artist:20}{Colors.ENDC} | "
                  f"📀 {Colors.WARNING}{album:<25}{Colors.ENDC} [{count} tracks]")

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
    ui = SnowskyUI()
    ui.print_header()
    
    # Initialize Downloader
    downloader = MusicDownloader()
    
    while True:
        ui.print_header()
        ui.print_menu(downloader)
        
        try:
            if HAS_RICH:
                choice = Console().input("[bold cyan]Choice: [/]")
            else:
                choice = input("Choice: ").strip()
                
            choice = choice.lower().strip()

            if choice == "1":
                if HAS_RICH:
                    folder_name = Console().input("[bold yellow]📁 Folder name (Artist/Album): [/]").strip()
                    link = Console().input("[bold yellow]🔗 YouTube/YT Music URL: [/]").strip()
                else:
                    folder_name = input("📁 Folder name (Artist/Album): ").strip()
                    link = input("🔗 YouTube/YT Music URL: ").strip()
                    
                if folder_name and link:
                    downloader.download_single_url(folder_name, link)
                    downloader.library = LibraryManager(DOWNLOAD_ROOT)

            elif choice == "2":
                if HAS_RICH:
                    playlist_name = Console().input("[bold yellow]📀 Playlist name: [/]").strip()
                    link = Console().input("[bold yellow]🔗 YouTube/YT Music playlist URL: [/]").strip()
                else:
                    playlist_name = input("📀 Playlist name: ").strip()
                    link = input("🔗 YouTube/YT Music playlist URL: ").strip()
                    
                if playlist_name and link:
                    downloader.download_playlist_url(playlist_name, link)
                    downloader.library = LibraryManager(DOWNLOAD_ROOT)
            
            elif choice == "3":
                if HAS_RICH:
                    playlist_name = Console().input("[bold yellow]🎧 Snowsky playlist: [/]").strip()
                else:
                    playlist_name = input("🎧 Snowsky playlist: ").strip()
                    
                if playlist_name:
                    downloader.interactive_playlist_selector(playlist_name)
                    downloader.library = LibraryManager(DOWNLOAD_ROOT)

            elif choice == "4":
                if HAS_RICH:
                    artist_name = Console().input("[bold yellow]🎤 Artist Name: [/]").strip()
                else:
                    artist_name = input("🎤 Artist Name: ").strip()
                    
                if artist_name:
                    print(f"{Colors.OKCYAN}Paste album URLs. Input 'Album Name' then 'URL'.")
                    print(f"Type 'GO' when finished.{Colors.ENDC}")
                    
                    queue = []
                    while True:
                        alb = input("💿 Album Name (or 'GO'): ").strip()
                        if alb.upper() == "GO":
                            break
                        if not alb:
                            continue
                        lnk = input("🔗 URL: ").strip()
                        if not lnk:
                            continue
                        
                        # Fix: Use Absolute Path for Batch Downloads
                        full_album_path = os.path.join(DOWNLOAD_ROOT, artist_name, alb)
                        queue.append((full_album_path, lnk))
                    
                    if queue:
                        downloader.download_queue_parallel(queue)
                        downloader.library = LibraryManager(DOWNLOAD_ROOT)

            elif choice == "v":
                ui.show_library_tree(DOWNLOAD_ROOT)

            elif choice == "9" or choice == "c":
                 downloader.cleanup_junk()

            elif choice == "m":
                downloader.mp3_mode = not downloader.mp3_mode
                CONFIG["mp3_mode"] = downloader.mp3_mode
                CONF_MANAGER.save_config()

            elif choice == "f":
                downloader.music_only = not downloader.music_only
                CONFIG["music_only"] = downloader.music_only
                CONF_MANAGER.save_config()

            elif choice == "l":
                downloader.lyrics_mode = not downloader.lyrics_mode
                CONFIG["lyrics_mode"] = downloader.lyrics_mode
                CONF_MANAGER.save_config()

            elif choice == "p":
                current = CONFIG.get("parallel_mode", True)
                CONFIG["parallel_mode"] = not current
                CONF_MANAGER.save_config()

            elif choice == "0":
                print("👋 Bye!")
                break

            if choice not in ["v", "0"]:
                input("\nPress Enter...")

        except KeyboardInterrupt:
            print("\n⚠️  Interrupted.")
            break
        except Exception as e:
            print(f"❌ Error: {e}")
            input("Press Enter...")

if __name__ == "__main__":
    main()
