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

class LiveStatus:
    """Simple, honest live status feed for a single download.

    Renders a numbered "track N of M" list that updates in place while
    downloading and commits to a new line whenever state actually changes.
    No fake percentages, no bar that can get stuck.
    """

    # ANSI escape codes
    _CLEAR_EOL = "\x1b[K"      # clear from cursor to end of line
    _MOVE_UP = "\x1b[A"        # move cursor up one line
    _HIDE_CURSOR = "\x1b[?25l"
    _SHOW_CURSOR = "\x1b[?25h"

    def __init__(self, header=None, total=1, stream=None):
        self.header = header
        self.total = max(int(total or 1), 1)
        self._stream = stream or sys.stdout
        self._current_line_printed = False
        self._last_status_line = ""  # remember for in-place updates
        self._lock = threading.Lock()

    def _print_header(self):
        if self.header:
            self._stream.write(f"{Colors.OKCYAN}{self.header}{Colors.ENDC}\n")
            self._stream.flush()

    def log(self, msg):
        """Print a status line that is NOT a per-track update."""
        with self._lock:
            if self._current_line_printed:
                # Erase the in-place line first, then print the new one
                self._stream.write(f"\r{self._CLEAR_EOL}\n{msg}\n")
                self._current_line_printed = False
            else:
                self._stream.write(f"{msg}\n")
            self._stream.flush()
        print(f"{msg}", flush=True)  # also to log

    def start_track(self, idx, title, total=None):
        """Show that a new track has started downloading."""
        with self._lock:
            if total:
                self.total = max(int(total), 1)
            line = f"  {Colors.WARNING}🎵 [{idx}/{self.total}]{Colors.ENDC} {title} {Colors.OKCYAN}downloading…{Colors.ENDC}"
            if self._current_line_printed:
                self._stream.write(f"\r{self._CLEAR_EOL}\n{line}\n")
            else:
                self._print_header()
                self._stream.write(f"{line}\n")
            self._last_status_line = line
            self._current_line_printed = True
            self._stream.flush()

    def finish_track(self, idx, title, size_str=""):
        """Show that the current track finished and was saved."""
        with self._lock:
            size_part = f" {Colors.OKGREEN}({size_str}){Colors.ENDC}" if size_str else ""
            line = f"  {Colors.OKGREEN}✅ [{idx}/{self.total}]{Colors.ENDC} {title} {Colors.OKGREEN}saved{size_part}{Colors.ENDC}"
            if self._current_line_printed:
                self._stream.write(f"\r{self._CLEAR_EOL}\n{line}\n")
            else:
                self._stream.write(f"{line}\n")
            self._last_status_line = line
            self._current_line_printed = False  # next call will commit, not overwrite
            self._stream.flush()

    def update_status(self, text):
        """Refresh the current 'downloading…' line in place with a sub-status."""
        with self._lock:
            if not self._current_line_printed:
                return
            self._last_status_line = text
            self._stream.write(f"\r{self._CLEAR_EOL}{text}")
            self._stream.flush()

    def finish(self, ok=True, elapsed_s=None):
        """Print a final summary line for this download."""
        with self._lock:
            if self._current_line_printed:
                self._stream.write(f"\r{self._CLEAR_EOL}\n")
                self._current_line_printed = False
            if elapsed_s is not None:
                sym = "🎉" if ok else "❌"
                self._stream.write(f"  {sym} Done in {elapsed_s:.1f}s\n")
            self._stream.flush()


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
        # Re-mux audio copy + attach picture (FLAC native METADATA_BLOCK_PICTURE)
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

    def _embed_cover_into_mp3(self, mp3_path, cover_jpg_500):
        # Attach cover as ID3v2 APIC frame; keep MP3 audio stream intact
        tmp = mp3_path + ".tmp.mp3"
        cmd = [
            FFMPEG_CMD, "-y",
            "-i", mp3_path,
            "-i", cover_jpg_500,
            "-map", "0:a",
            "-map", "1:v",
            "-c:a", "copy",
            "-c:v", "copy",
            "-id3v2_version", "3",
            "-metadata:s:v", "title=Album cover",
            "-metadata:s:v", "comment=Cover (front)",
            "-disposition:v:0", "attached_pic",
            tmp
        ]
        self._run(cmd)
        safe_file_op(os.replace, tmp, mp3_path)

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
            # Dispatch to the correct embedder based on file extension
            ext = os.path.splitext(filepath)[1].lower()
            if ext == ".mp3":
                self._embed_cover_into_mp3(filepath, cover500)
            else:
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

    # ---------- yt-dlp line parser ----------
    # Recognized event types for the multi-signal progress system.
    # Each event: ("TYPE", payload_dict)
    progress_pattern = re.compile(
        r'\[download\]\s+(\d+\.?\d*)%\s+of\s+~?(\S+)\s+at\s+(\S+)\s+ETA\s+(\S+)'
    )
    simple_pattern = re.compile(r'\[download\]\s+(\d+\.?\d*)%')
    YT_PATTERN_PLAYLIST = re.compile(
        r'\[download\]\s+Downloading\s+playlist:\s+(.+?)(?:\s*-\s*(\d+)\s+videos?)?$',
        re.IGNORECASE
    )
    YT_PATTERN_ITEM = re.compile(
        r'\[download\]\s+Downloading\s+item\s+(\d+)\s+of\s+(\d+)',
        re.IGNORECASE
    )
    YT_PATTERN_DESTINATION = re.compile(
        r'\[ExtractAudio\]\s+Destination:\s+(.+)$',
        re.IGNORECASE
    )
    YT_PATTERN_EXTRACTING = re.compile(
        r'\[youtube\]\s+Extracting\s+URL',
        re.IGNORECASE
    )
    YT_PATTERN_POSTPROCESS = re.compile(
        r'\[(?:Fixup|EmbedSubtitle|Metadata|ThumbnailsConvertor|Exec)',
        re.IGNORECASE
    )

    def _parse_ytdlp_line(self, line):
        """Return (event_type, payload) tuple, or (None, None) if unrecognized."""
        s = line.strip()
        if not s:
            return (None, None)

        # Detailed progress: [download]  45.0% of   3.45MiB at    2.00MiB/s ETA 00:01
        m = self.progress_pattern.search(s)
        if m:
            try:
                return ("DOWNLOAD_PCT", {
                    "percent": float(m.group(1)),
                    "speed": m.group(3),
                    "eta": m.group(4),
                })
            except (ValueError, IndexError):
                pass

        # Simple percent fallback: [download]  12.0%
        m = self.simple_pattern.search(s)
        if m:
            try:
                return ("DOWNLOAD_PCT", {
                    "percent": float(m.group(1)),
                    "speed": "",
                    "eta": "",
                })
            except ValueError:
                pass

        # Per-item counter in a playlist
        m = self.YT_PATTERN_ITEM.search(s)
        if m:
            return ("ITEM_START", {
                "index": int(m.group(1)),
                "total": int(m.group(2)),
            })

        # Playlist header
        m = self.YT_PATTERN_PLAYLIST.search(s)
        if m:
            return ("PLAYLIST_START", {
                "name": m.group(1).strip(),
                "count": int(m.group(2)) if m.group(2) else 0,
            })

        # Audio extraction finished
        m = self.YT_PATTERN_DESTINATION.search(s)
        if m:
            return ("EXTRACT", {
                "destination": m.group(1).strip(),
            })

        # Phase hints
        if self.YT_PATTERN_EXTRACTING.search(s):
            return ("PHASE", {"name": "🔍 Extracting URL…"})
        if "[youtube]" in s.lower() and "downloading webpage" in s.lower():
            return ("PHASE", {"name": "🌐 Fetching webpage…"})
        if "[youtube]" in s.lower() and ("downloading m3u8" in s.lower() or "downloading manifest" in s.lower()):
            return ("PHASE", {"name": "📜 Fetching manifest…"})
        if "generic" in s.lower() and "extracting" in s.lower():
            return ("PHASE", {"name": "🔧 Resolving formats…"})
        if self.YT_PATTERN_POSTPROCESS.search(s):
            return ("PHASE", {"name": "⚙️ Post-processing…"})

        return (None, None)

    # ---------- execution wrapper ----------
    def _run_download(self, folder, link, playlist_mode=False, quiet=False, progress=None, task_id=None):
        os.makedirs(folder, exist_ok=True)
        link = clean_url(link)
        fmt = "MP3" if self.mp3_mode else "FLAC"

        # The caller can pass in a pre-created LiveStatus (used for the
        # parallel batch flow), or we create one here for single downloads.
        live = progress if isinstance(progress, LiveStatus) else None
        owning_live = False
        if live is None:
            header = f"⬇️ {os.path.basename(folder)} ({fmt})"
            if not quiet:
                # quiet=False path: use the old Spinner so non-quiet keeps the
                # current "yt-dlp processing..." style. We don't create a live
                # feed in this mode (it would be redundant with the print()s).
                print(f"{Colors.OKGREEN}🎵 {header}{Colors.ENDC}")
                print(f"{Colors.OKCYAN}🔗 {link}{Colors.ENDC}")
                spinner = Spinner()
                spinner.start(f"yt-dlp processing…")
        elif progress and task_id:
            # Legacy Rich path still works (compatibility)
            progress.update(task_id, description=f"⬇️ {os.path.basename(folder)} (yt-dlp)")

        # Template from Config
        tmpl_str = CONFIG.get("filename_template", "%(playlist_index|00|)s %(title)s.%(ext)s")
        outtmpl = os.path.join(folder, tmpl_str)

        cmd = self._yt_dlp_cmd(outtmpl, link, "mp3" if self.mp3_mode else "flac")

        start_ts = time.time()
        # In live mode, the live object handles the header itself
        if live:
            live.log(f"{Colors.OKCYAN}🔗 {link}{Colors.ENDC}")

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1,
            )

            # Per-track state
            full_output = []
            state = {
                "item_index": 0,          # 0 until we know the playlist total
                "item_total": 0,
                "last_track_title": "",   # last track name we displayed
            }

            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break

                if line:
                    full_output.append(line)
                    event_type, payload = self._parse_ytdlp_line(line)
                    if event_type is None:
                        continue

                    if live is None:
                        # Non-live (legacy Rich bar) or quiet=False path:
                        # keep the old bar behavior so we don't regress.
                        if progress and task_id and event_type == "DOWNLOAD_PCT":
                            pct = payload.get("percent", 0.0)
                            progress.update(
                                task_id,
                                completed=pct,
                                description=f"⬇️ {os.path.basename(folder)}",
                                speed=payload.get("speed", ""),
                                eta=payload.get("eta", ""),
                            )
                        continue

                    # ----- LiveStatus path -----
                    if event_type == "PLAYLIST_START":
                        if payload.get("count"):
                            state["item_total"] = int(payload["count"])
                        live.log(f"  📜 {payload.get('name', '')}")
                        if state["item_total"]:
                            live.log(f"  {Colors.OKCYAN}Found {state['item_total']} tracks{Colors.ENDC}")

                    elif event_type == "ITEM_START":
                        state["item_index"] = int(payload["index"])
                        state["item_total"] = int(payload["total"])
                        title = f"Track {state['item_index']}"
                        live.start_track(state["item_index"], title, total=state["item_total"])

                    elif event_type == "EXTRACT":
                        dest = os.path.basename(payload.get("destination", ""))
                        state["last_track_title"] = dest
                        # Use whatever item_index we have; fall back to 1 for single URLs
                        idx = state["item_index"] if state["item_index"] else 1
                        total = state["item_total"] if state["item_total"] else 1
                        try:
                            size_str = self._human_size(dest)
                        except Exception:
                            size_str = ""
                        live.finish_track(idx, dest, size_str=size_str)

                    elif event_type == "PHASE":
                        # Show phase above the in-place line if we have a current track
                        if state["item_index"] and state["item_total"]:
                            live.update_status(
                                f"  {Colors.WARNING}🎵 [{state['item_index']}/{state['item_total']}]{Colors.ENDC} "
                                f"{payload.get('name', '')}"
                            )

                    elif event_type == "DOWNLOAD_PCT":
                        # Refine the in-place line with speed/ETA (when we have a track)
                        if state["item_index"] and state["item_total"]:
                            speed = payload.get("speed", "")
                            eta = payload.get("eta", "")
                            tail = f"{speed}" + (f" • ETA {eta}" if eta else "")
                            live.update_status(
                                f"  {Colors.WARNING}🎵 [{state['item_index']}/{state['item_total']}]{Colors.ENDC} "
                                f"{state['last_track_title'] or ''} {Colors.OKCYAN}{tail}{Colors.ENDC}"
                            )

            stdout = "".join(full_output)
            elapsed = time.time() - start_ts

            if process.returncode != 0:
                if not quiet and 'spinner' in locals():
                    spinner.stop(False)

                out_lower = stdout.lower() if stdout else ""
                produced_files = any(
                    f.endswith('.flac') or f.endswith('.mp3')
                    for f in os.listdir(folder)
                )

                if "does not match filter" in out_lower:
                    if not quiet: print(f"{Colors.WARNING}⏭️  Skipped (Not a music track/filter mismatch){Colors.ENDC}")
                elif "video unavailable" in out_lower or "403" in out_lower:
                    if not quiet: print(f"{Colors.WARNING}⏭️  Skipped (Unavailable/Forbidden - Check Cookies){Colors.ENDC}")
                else:
                    if not quiet:
                        print(f"{Colors.FAIL}❌ yt-dlp warning/error:{Colors.ENDC}")
                        print(stdout)
                    logging.error(f"yt-dlp error for {link}: {stdout}")

                if not produced_files:
                    if live: live.finish(ok=False, elapsed_s=elapsed)
                    return False

            # ---- Post-process: covers ----
            if live:
                live.log(f"  {Colors.OKCYAN}🖼️  Embedding covers…{Colors.ENDC}")
            elif not quiet:
                spinner.start("Fixing covers…")
            elif progress and task_id:
                progress.update(task_id, description=f"🖼️ Covers: {os.path.basename(folder)}")

            self._fix_all_covers(folder)

            # ---- Post-process: lyrics/cleanup ----
            if live:
                live.log(f"  {Colors.OKCYAN}📝 Fetching lyrics…{Colors.ENDC}")
            elif not quiet:
                spinner.update("Post-processing (Lyrics & Cleanup)…")
            self._post_process_downloads(folder, spinner if not quiet else None, quiet=quiet)

            if not quiet and 'spinner' in locals():
                spinner.stop(True)
            if live:
                live.finish(ok=True, elapsed_s=elapsed)
            return True

        except Exception as e:
            if not quiet and 'spinner' in locals():
                spinner.stop(False)
            print(f"{Colors.FAIL}❌ Error: {e}{Colors.ENDC}")
            logging.error(f"Download Exception {link}: {e}")
            if live:
                live.finish(ok=False, elapsed_s=time.time() - start_ts)
            return False

    @staticmethod
    def _human_size(filename):
        """Return human size for a finished file (or '' if missing)."""
        try:
            if os.path.exists(filename):
                sz = os.path.getsize(filename)
                for unit in ("B", "KiB", "MiB", "GiB"):
                    if sz < 1024:
                        return f"{sz:.1f} {unit}"
                    sz /= 1024
                return f"{sz:.1f} TiB"
        except Exception:
            pass
        return ""

    def download_queue_parallel(self, queue_items):
        """
        queue_items: list of (folder_path, url)
        Honest live feed: no fake bar, no Rich Progress wrapper.
        Each album prints its own per-track status; a running total is
        shown between albums.
        """
        if not queue_items: return

        parallel = CONFIG.get("parallel_mode", True)
        workers = CONFIG["max_workers"] if parallel else 1
        mode_str = "Parallel" if parallel else "Single-Threaded"

        sys.stdout.write(
            f"\n{Colors.HEADER}🚀 Starting Batch ({len(queue_items)} albums) "
            f"| Mode: {mode_str} | Threads: {workers}{Colors.ENDC}\n"
        )
        sys.stdout.flush()

        start_time = time.time()
        success_count = 0
        fail_count = 0
        idx_lock = threading.Lock()
        done = [0]  # mutable counter for completed albums

        def _run_one(album_idx, folder, url):
            # Print a clear header for this album
            album_name = os.path.basename(folder)
            sys.stdout.write(
                f"\n{Colors.OKCYAN}── Album {album_idx}/{len(queue_items)}: "
                f"{album_name} ──{Colors.ENDC}\n"
            )
            sys.stdout.flush()

            live = LiveStatus(stream=sys.stdout)
            ok = False
            try:
                ok = self._run_download(
                    folder, url, quiet=True,
                    progress=live, task_id=None,
                )
            except Exception as e:
                logging.error(f"Album {album_idx} failed: {e}")
                ok = False
            finally:
                with idx_lock:
                    done[0] += 1
                    pct = done[0] * 100 // len(queue_items)
                sys.stdout.write(
                    f"  {Colors.OKCYAN}📦 Albums done: "
                    f"{done[0]}/{len(queue_items)} ({pct}%){Colors.ENDC}\n"
                )
                sys.stdout.flush()
            return ok

        if parallel and workers > 1:
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [
                    executor.submit(_run_one, i + 1, folder, url)
                    for i, (folder, url) in enumerate(queue_items)
                ]
                for fut in concurrent.futures.as_completed(futures):
                    try:
                        if fut.result():
                            success_count += 1
                        else:
                            fail_count += 1
                    except Exception as e:
                        logging.error(f"Worker exception: {e}")
                        fail_count += 1
        else:
            # Serial: one album at a time
            for i, (folder, url) in enumerate(queue_items):
                if _run_one(i + 1, folder, url):
                    success_count += 1
                else:
                    fail_count += 1

        elapsed = time.time() - start_time
        sym = "🎉" if fail_count == 0 else "⚠️ "
        sys.stdout.write(
            f"\n{Colors.OKGREEN}{sym} Batch done in {elapsed:.1f}s — "
            f"{success_count} OK, {fail_count} failed{Colors.ENDC}\n"
        )
        sys.stdout.flush()

    def _parallel_worker(self, folder, url, live):
        """Worker for the parallel batch: prints to the shared LiveStatus feed."""
        try:
            return self._run_download(folder, url, quiet=True, progress=live, task_id=None)
        except Exception as e:
            logging.error(f"Worker failed: {e}")
            return False

    def _fetch_playlist_title(self, url):
        """Use yt-dlp to quickly fetch the playlist/video title without downloading.
        Returns the title string, or None on failure."""
        try:
            result = subprocess.run(
                [
                    YT_DLP_CMD,
                    "--flat-playlist",
                    "--dump-single-json",
                    "--no-warnings",
                    "--playlist-items", "0",  # metadata only, no items
                    url,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
            )
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout.strip())
                return data.get("title") or data.get("playlist_title") or None
        except Exception:
            pass
        return None

    def download_single_url(self, folder_name, url):
        """Single URL download. Uses a LiveStatus feed for honest progress."""
        full_path = os.path.join(DOWNLOAD_ROOT, folder_name)
        live = LiveStatus(header=f"⬇️ {folder_name}")
        return self._run_download(full_path, url, quiet=True, progress=live, task_id=None)

    def download_playlist_url(self, playlist_name, url):
        """Playlist download. Uses a LiveStatus feed for honest progress."""
        full_path = os.path.join(DOWNLOAD_ROOT, "Playlists", playlist_name)
        live = LiveStatus(header=f"⬇️ Playlists/{playlist_name}")
        return self._run_download(full_path, url, quiet=True, progress=live, task_id=None)

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
                # Ask for URL first so we can auto-fetch the title
                if HAS_RICH:
                    link = Console().input("[bold yellow]🔗 YouTube/YT Music URL: [/]").strip()
                else:
                    link = input("🔗 YouTube/YT Music URL: ").strip()

                if link:
                    fetched_title = None
                    spinner = Spinner()
                    spinner.start("🔍 Fetching title…")
                    try:
                        fetched_title = downloader._fetch_playlist_title(link)
                    finally:
                        spinner.stop(fetched_title is not None)

                    if fetched_title:
                        print(f"{Colors.OKCYAN}📁 Detected title: {Colors.OKGREEN}{fetched_title}{Colors.ENDC}")
                        if HAS_RICH:
                            custom = Console().input(
                                f"[bold yellow]📁 Folder name [Enter to use '{fetched_title}']: [/]"
                            ).strip()
                        else:
                            custom = input(f"📁 Folder name [Enter to use '{fetched_title}']: ").strip()
                        folder_name = custom if custom else fetched_title
                    else:
                        print(f"{Colors.WARNING}⚠️  Could not auto-fetch title. Please enter one manually.{Colors.ENDC}")
                        if HAS_RICH:
                            folder_name = Console().input("[bold yellow]📁 Folder name (Artist/Album): [/]").strip()
                        else:
                            folder_name = input("📁 Folder name (Artist/Album): ").strip()

                    if folder_name:
                        downloader.download_single_url(folder_name, link)
                        downloader.library = LibraryManager(DOWNLOAD_ROOT)

            elif choice == "2":
                # Ask for URL first so we can auto-fetch the title
                if HAS_RICH:
                    link = Console().input("[bold yellow]🔗 YouTube/YT Music playlist URL: [/]").strip()
                else:
                    link = input("🔗 YouTube/YT Music playlist URL: ").strip()

                if link:
                    # Auto-fetch playlist title as default name
                    fetched_title = None
                    spinner = Spinner()
                    spinner.start("🔍 Fetching playlist title…")
                    try:
                        fetched_title = downloader._fetch_playlist_title(link)
                    finally:
                        spinner.stop(fetched_title is not None)

                    if fetched_title:
                        print(f"{Colors.OKCYAN}📀 Detected title: {Colors.OKGREEN}{fetched_title}{Colors.ENDC}")
                        if HAS_RICH:
                            custom = Console().input(
                                f"[bold yellow]📀 Playlist name [Enter to use '{fetched_title}']: [/]"
                            ).strip()
                        else:
                            custom = input(f"📀 Playlist name [Enter to use '{fetched_title}']: ").strip()
                        playlist_name = custom if custom else fetched_title
                    else:
                        # Fallback: no title found, ask manually
                        print(f"{Colors.WARNING}⚠️  Could not auto-fetch title. Please enter one manually.{Colors.ENDC}")
                        if HAS_RICH:
                            playlist_name = Console().input("[bold yellow]📀 Playlist name: [/]").strip()
                        else:
                            playlist_name = input("📀 Playlist name: ").strip()

                    if playlist_name:
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
                    print(f"{Colors.OKCYAN}Paste album URLs one at a time. Type 'GO' when finished.{Colors.ENDC}")
                    
                    queue = []
                    while True:
                        lnk = input("🔗 Album URL (or 'GO'): ").strip()
                        if lnk.upper() == "GO":
                            break
                        if not lnk:
                            continue

                        # Auto-fetch album title
                        fetched_alb = None
                        spinner = Spinner()
                        spinner.start("🔍 Fetching album title…")
                        try:
                            fetched_alb = downloader._fetch_playlist_title(lnk)
                        finally:
                            spinner.stop(fetched_alb is not None)

                        if fetched_alb:
                            print(f"{Colors.OKCYAN}💿 Detected album: {Colors.OKGREEN}{fetched_alb}{Colors.ENDC}")
                            alb = input(f"💿 Album name [Enter to use '{fetched_alb}']: ").strip()
                            alb = alb if alb else fetched_alb
                        else:
                            print(f"{Colors.WARNING}⚠️  Could not auto-fetch album title.{Colors.ENDC}")
                            alb = input("💿 Album Name: ").strip()

                        if not alb:
                            continue

                        # Fix: Use Absolute Path for Batch Downloads
                        full_album_path = os.path.join(DOWNLOAD_ROOT, artist_name, alb)
                        queue.append((full_album_path, lnk))
                        print(f"{Colors.OKGREEN}  ✅ Queued: {artist_name} / {alb}{Colors.ENDC}")
                    
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
