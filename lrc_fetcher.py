import os
import sys
import glob
import requests
import json
import subprocess
import shutil
import time
from pathlib import Path

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

class LRCFetcher:
    def __init__(self):
        self.session = requests.Session()
        self.ffprobe_cmd = self._find_ffprobe()
        
    def _find_ffprobe(self):
        """Find ffprobe in PATH or common locations."""
        if shutil.which("ffprobe"):
            return "ffprobe"
            
        # Check local directory or recursive search (similar to batchdl)
        # For now, simplistic check. If not found, we'll try to rely on filename parsing or warn user.
        print(f"{Colors.WARNING}⚠️  ffprobe not found in PATH. Metadata extraction might fail.{Colors.ENDC}")
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
                    data = json.loads(result.stdout)
                    tags = data.get("format", {}).get("tags", {})
                    # Keys can be case insensitive in some formats, but usually lowercase in ffmpeg json
                    # ffmpeg keys are usually: artist, title, album (or ALBUM, ARTIST)
                    # Normalize keys to lower
                    tags_lower = {k.lower(): v for k, v in tags.items()}
                    
                    meta["artist"] = tags_lower.get("artist") or tags_lower.get("album_artist")
                    meta["title"] = tags_lower.get("title")
                    meta["album"] = tags_lower.get("album")
            except Exception as e:
                pass # Fallback to filename

        # 2. Fallback: Filename parsing
        # Expect "Artist - Title.ext" or "01 Title.ext"
        if not meta["artist"] or not meta["title"]:
            filename = os.path.splitext(os.path.basename(filepath))[0]
            # Try splitting by " - "
            parts = filename.split(" - ")
            if len(parts) >= 2:
                # Assume Artist - Title
                if not meta["artist"]: meta["artist"] = parts[0].strip()
                if not meta["title"]: meta["title"] = " - ".join(parts[1:]).strip()
            else:
                # Maybe "01 Title"
                # Remove leading numbers
                cleaned = filename
                while len(cleaned) > 0 and cleaned[0].isdigit():
                    cleaned = cleaned[1:]
                
                cleaned = cleaned.strip(" .-_")
                if not meta["title"]: meta["title"] = cleaned
                
        return meta

    def _get_artist_candidates(self, artist_raw):
        """Generate a list of artist variants to try."""
        candidates = [artist_raw]
        
        # Split by comma
        if "," in artist_raw:
            candidates.append(artist_raw.split(",")[0].strip())
            
        # Split by " & " or " and "
        if " & " in artist_raw:
            candidates.append(artist_raw.split(" & ")[0].strip())
        
        # Split by " x " (common in collabs)
        if " x " in artist_raw.lower():
            candidates.append(re.split(r" [xX] ", artist_raw)[0].strip())

        # Deduplicate while preserving order
        unique_candidates = []
        for c in candidates:
            if c and c not in unique_candidates:
                unique_candidates.append(c)
                
        return unique_candidates

    def fetch_lrc(self, artist, title, album, save_path):
        """Fetch LRC from LRCLIB with fallback search strategies."""
        if not artist or not title:
            print(f"  {Colors.WARNING}⚠️  Missing artist or title, skipping.{Colors.ENDC}")
            return False

        candidates = self._get_artist_candidates(artist)
        
        for i, try_artist in enumerate(candidates):
            prefix = "  " if i == 0 else f"  {Colors.WARNING}↳ Retry ({try_artist}):{Colors.ENDC} "
            
            # Try exact match first
            url_get = "https://lrclib.net/api/get"
            params = {"artist_name": try_artist, "track_name": title}
            if album:
                params["album_name"] = album
                
            try:
                resp = self.session.get(url_get, params=params, timeout=10)
                data = None
                
                if resp.status_code == 200:
                    data = resp.json()
                elif resp.status_code == 404:
                    # Search fallback
                    url_search = "https://lrclib.net/api/search"
                    q = f"{try_artist} {title}"
                    resp_search = self.session.get(url_search, params={"q": q}, timeout=10)
                    if resp_search.status_code == 200:
                        results = resp_search.json()
                        if results:
                            data = results[0] # Pick first result
                
                if data:
                    lrc_content = data.get("syncedLyrics", "") or data.get("plainLyrics", "")
                    
                    if lrc_content:
                        with open(save_path, "w", encoding="utf-8") as f:
                            f.write(lrc_content)
                        print(f"{prefix}{Colors.OKGREEN}✅ Found: {title}{Colors.ENDC}")
                        return True
                    else:
                        if i == len(candidates) - 1:
                            print(f"{prefix}{Colors.FAIL}❌ No lyrics content.{Colors.ENDC}")
                else:
                    if i == len(candidates) - 1: # Last attempt
                        print(f"{prefix}{Colors.FAIL}❌ Not found.{Colors.ENDC}")
                    
            except Exception as e:
                print(f"{prefix}{Colors.FAIL}❌ Error: {e}{Colors.ENDC}")
                
        return False

    def scan_folder(self, folder_path):
        folder = Path(folder_path)
        if not folder.exists():
            print(f"{Colors.FAIL}❌ Folder not found!{Colors.ENDC}")
            return

        print(f"\n{Colors.HEADER}📂 Scanning: {folder}{Colors.ENDC}")
        extensions = ['*.mp3', '*.flac', '*.m4a', '*.wav', '*.ogg', '*.opus']
        files = []
        for ext in extensions:
            files.extend(list(folder.glob(ext))) # Not recursive by default for album safety
            
        if not files:
            print(f"{Colors.WARNING}No audio files found.{Colors.ENDC}")
            return

        print(f"Found {len(files)} audio files.")
        
        for filepath in files:
            # Check if lrc exists
            lrc_path = filepath.with_suffix(".lrc")
            if lrc_path.exists():
                print(f"{Colors.OKBLUE}⏭️  Exists: {filepath.name}{Colors.ENDC}")
                continue
                
            print(f"Processing: {filepath.name}")
            meta = self.get_metadata(str(filepath))
            
            artist = meta["artist"]
            title = meta["title"]
            album = meta["album"]
            
            print(f"  🔍 Query: {artist} - {title} (Alb: {album})")
            
            # If we don't have artist/title, ask user? Or skip?
            # For automation, we skip if absolutely unknown, but get_metadata tries hard.
            
            self.fetch_lrc(artist, title, album, lrc_path)
            time.sleep(0.5) # Rate limit politeness

def main():
    print(f"{Colors.HEADER}🎤 LRCLIB FETCHER TOOL{Colors.ENDC}")
    print("="*50)
    
    fetcher = LRCFetcher()
    
    while True:
        print(f"\n{Colors.OKCYAN}1. Scan a folder (Album/Playlist){Colors.ENDC}")
        print(f"{Colors.OKCYAN}2. Single Song (Manual Entry){Colors.ENDC}")
        print("0. Exit")
        
        choice = input("\nChoice: ").strip()
        
        if choice == "1":
            path = input("Enter folder path: ").strip().strip('"') # Remove quotes if pasted
            fetcher.scan_folder(path)
            
        elif choice == "2":
            artist = input("Artist: ").strip()
            title = input("Title: ").strip()
            album = input("Album (Optional): ").strip()
            save_path = f"{artist} - {title}.lrc".replace("/", "_").replace("\\", "_")
            fetcher.fetch_lrc(artist, title, album, save_path)
            
        elif choice == "0":
            break
        else:
            print("Invalid.")

if __name__ == "__main__":
    main()
