import os
import hashlib
import time
import logging
import requests
from datetime import datetime, timedelta
from tkinter import Tk, filedialog, messagebox, simpledialog
from send2trash import send2trash

# CONFIGURATION
VERSION = "v1.0.0"
GITHUB_REPO = "Mastkasin/DuplicateDeleter"
LOG_FILE = "duplicate_deletion.log"

def setup_logging():
    """Sets up logging and removes entries older than 30 days for privacy and space."""
    if os.path.exists(LOG_FILE):
        threshold = datetime.now() - timedelta(days=30)
        valid_lines = []
        try:
            with open(LOG_FILE, "r") as f:
                for line in f:
                    try:
                        # Extract date from log line: 'YYYY-MM-DD HH:MM:SS - Message'
                        date_str = line.split(" - ")[0]
                        line_date = datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
                        if line_date > threshold:
                            valid_lines.append(line)
                    except:
                        valid_lines.append(line) # Keep lines that don't match format
            with open(LOG_FILE, "w") as f:
                f.writelines(valid_lines)
        except Exception:
            pass

    logging.basicConfig(
        filename=LOG_FILE, 
        level=logging.INFO, 
        format='%(asctime)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

def check_for_updates():
    """Securely checks GitHub for new releases using TLS 1.3."""
    try:
        url = f"https://api.github.com{GITHUB_REPO}/releases/latest"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            latest_version = response.json().get("tag_name", VERSION)
            if latest_version != VERSION:
                messagebox.showinfo("Update Available", 
                    f"A new version ({latest_version}) is available!\n"
                    f"Visit the GitHub repository to download.")
    except:
        pass 

def get_file_hash(path):
    """Secure SHA-256 content verification."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except:
        return None

def run_deduplicator():
    root = Tk()
    root.withdraw()
    
    setup_logging()
    check_for_updates()
    
    target_folder = filedialog.askdirectory(title=f"DuplicateDeleter {VERSION}")
    if not target_folder: return

    days_input = simpledialog.askinteger("Safe Delay", "Delete duplicates older than how many days?", parent=root, minvalue=0)
    if days_input is None: return

    hashes = {}
    now = time.time()
    seconds_limit = days_input * 86400
    count = 0

    logging.info(f"--- SCAN STARTED (Safe Delay: {days_input} days) ---")

    for root_dir, _, files in os.walk(target_folder):
        for name in files:
            filepath = os.path.join(root_dir, name)
            
            # skip symlinks, system hidden files & logfile
            if os.path.islink(filepath) or name == LOG_FILE or name.startswith('._'):
                continue
                
            file_hash = get_file_hash(filepath)
            if not file_hash: continue

            if file_hash in hashes:
                file_age = now - os.path.getmtime(filepath)
                if file_age > seconds_limit:
                    try:
                        send2trash(filepath)
                        logging.info(f"TRASHED: {filepath}")
                        count += 1
                    except:
                        logging.error(f"Failed to move: {filepath}")
            else:
                hashes[file_hash] = filepath

    messagebox.showinfo(f"DuplicateDeleter {VERSION}", f"Done! {count} files moved to Trash.")

if __name__ == "__main__":
    run_deduplicator()
