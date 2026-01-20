import sys
import os

# Ensure we can import batchdl
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from batchdl import MusicDownloader

def main():
    folder = r"C:\Users\marco\Music\batchdl\Playlists\old opm songs v2"
    print(f"Fixing folder: {folder}")
    
    if not os.path.exists(folder):
        print(f"Error: Folder not found: {folder}")
        return

    dl = MusicDownloader()
    
    # 1. Embed Covers
    print("Embedding covers...")
    dl._fix_all_covers(folder)
    
    # 2. Fetch Lyrics & Clean JSON
    print("Fetching lyrics and cleaning JSON...")
    # Passing None as spinner since the function doesn't use it
    dl._fetch_lrc_and_cleanup(folder, None)
        
    print("Done!")

if __name__ == "__main__":
    main()
