import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
import hashlib
import logging
import json
import platform
import threading
import multiprocessing
import sys
import subprocess
import webbrowser
from send2trash import send2trash

# Background Tray Icon libraries
import pystray
from pystray import MenuItem as item
from PIL import Image, ImageDraw

# ==========================================
# CONFIGURATION, PATHS & THEME
# ==========================================
VERSION = "v4.0.0"
LOG_FILENAME = "DuplicateDeleter.log"
CONFIG_FILENAME = "DuplicateDeleter_config.json"

home_dir = os.path.expanduser("~")
downloads_dir = os.path.join(home_dir, "Downloads")
if not os.path.exists(downloads_dir):
    downloads_dir = home_dir

log_file_path = os.path.join(downloads_dir, LOG_FILENAME)
config_file_path = os.path.join(home_dir, CONFIG_FILENAME)

# Logging Setup
logging.basicConfig(
    filename=log_file_path, 
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Theme Colors (Google Drive Dark Mode inspired)
BG_MAIN = "#1f1f1f"
BG_SIDEBAR = "#121212"
BG_TOPBAR = "#181818"
BG_SEARCH = "#303134"
FG_TEXT = "#e8eaed"
FG_TEXT_MUTED = "#9aa0a6"
ACCENT_BLUE = "#8ab4f8"
ACCENT_GREEN = "#81c995"
ACCENT_YELLOW = "#fde293"

FONT_MAIN = ("Segoe UI", 10) if platform.system() == "Windows" else ("Helvetica", 11)
FONT_TITLE = ("Segoe UI", 16, "bold") if platform.system() == "Windows" else ("Helvetica", 16, "bold")
FONT_LARGE = ("Segoe UI", 20, "bold") if platform.system() == "Windows" else ("Helvetica", 20, "bold")

def log_record(status, name, filepath):
    """Writes a standardized parseable line to the log for the Duplicates view."""
    logging.info(f"RECORD|{status}|{name}|{filepath}")

# ==========================================
# ISOLATED MACOS TRAY PROCESS
# ==========================================
def run_mac_tray_process(conn):
    """Runs completely isolated on macOS using a Pipe to prevent AppKit crashes."""
    def on_open(icon, item): conn.send("TOGGLE_DASHBOARD")
    def on_toggle_autocull(icon, item): conn.send("DISABLE_AUTOCULL_QUIT")
    def on_icon_click(icon): conn.send("FORCE_FOREGROUND")

    image = Image.new('RGB', (64, 64), color=(147, 51, 234))
    draw = ImageDraw.Draw(image)
    draw.ellipse((16, 16, 48, 48), fill=(255, 255, 255))
    
    menu = pystray.Menu(
        item('Open Dashboard', on_open),
        pystray.Menu.SEPARATOR,
        item('Auto-Cull Enabled (Click to Quit)', on_toggle_autocull)
    )
    icon = pystray.Icon("DuplicateDeleter", image, "DuplicateDeleter", menu, action=on_icon_click)
    icon.run()

# ==========================================
# MAIN APPLICATION CLASS
# ==========================================
class DuplicateDeleterApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"DuplicateDeleter {VERSION}")
        self.root.geometry("1000x700")
        self.root.configure(bg=BG_MAIN)
        self.root.protocol('WM_DELETE_WINDOW', self.hide_window)
        
        self.monitored_folders = []
        self.ignored_hashes = set() 
        self.auto_cull_ms = 0 
        self.saved_auto_cull_ms = 0 
        self.after_id = None 
        
        self.tray_icon = None
        self.parent_conn, self.child_conn = multiprocessing.Pipe(duplex=False)
        self.tray_process = None
        
        self.setup_styles()
        self.setup_layout()
        self.load_config()
        self.enable_system_startup() 
        
        self.setup_tray_icon()
        self.poll_queue()
        
        self.switch_to_homepage()

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('default')
        style.configure("Treeview", background=BG_MAIN, foreground=FG_TEXT, fieldbackground=BG_MAIN, borderwidth=0, font=FONT_MAIN)
        style.map('Treeview', background=[('selected', '#3f4147')])
        
        # Heading styles (Configure background and foreground for active/hover status to prevent whitening)
        style.configure("Treeview.Heading", background=BG_SIDEBAR, foreground=FG_TEXT, borderwidth=0, font=FONT_MAIN)
        style.map("Treeview.Heading",
                  background=[('pressed', BG_TOPBAR), ('active', '#2a2a2a')],
                  foreground=[('pressed', ACCENT_BLUE), ('active', ACCENT_BLUE)])

    def setup_layout(self):
        # Top Bar
        self.top_bar = tk.Frame(self.root, bg=BG_TOPBAR, height=60)
        self.top_bar.pack(side="top", fill="x")
        self.top_bar.pack_propagate(False)
        
        self.lbl_logo = tk.Label(self.top_bar, text="DuplicateDeleter", font=FONT_TITLE, bg=BG_TOPBAR, fg=FG_TEXT, cursor="hand2")
        self.lbl_logo.pack(side="left", padx=20, pady=15)
        self.lbl_logo.bind("<Button-1>", lambda e: webbrowser.open("https://github.com/Mastkasin/DuplicateDeleter/"))
        self.lbl_logo.bind("<Enter>", lambda e: self.lbl_logo.config(fg=ACCENT_BLUE))
        self.lbl_logo.bind("<Leave>", lambda e: self.lbl_logo.config(fg=FG_TEXT))
        
        # Search Bar
        search_frame = tk.Frame(self.top_bar, bg=BG_SEARCH, padx=10, pady=5)
        search_frame.pack(side="left", padx=20, pady=10, fill="y")
        
        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(search_frame, textvariable=self.search_var, bg=BG_SEARCH, fg=FG_TEXT, 
                                     insertbackground=FG_TEXT, bd=0, highlightthickness=0, font=FONT_MAIN, width=40)
        self.search_entry.insert(0, "Search in log")
        self.search_entry.bind("<FocusIn>", lambda e: self.search_entry.delete(0, 'end') if self.search_entry.get() == "Search in log" else None)
        self.search_entry.bind("<FocusOut>", lambda e: self.search_entry.insert(0, "Search in log") if not self.search_entry.get() else None)
        self.search_entry.bind("<Return>", lambda e: self.switch_to_search_results())
        self.search_entry.pack(side="left", fill="both", expand=True)

        # Main Body (Sidebar + Content)
        self.body_frame = tk.Frame(self.root, bg=BG_MAIN)
        self.body_frame.pack(side="top", fill="both", expand=True)
        
        # Sidebar
        self.sidebar = tk.Frame(self.body_frame, bg=BG_SIDEBAR, width=220)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        
        # Labels as buttons for better cross-platform display
        self.btn_nav_home = tk.Label(self.sidebar, text="🏠 Homepage", font=FONT_MAIN, bg=BG_SIDEBAR, fg=FG_TEXT, 
                                     anchor="w", padx=20, pady=10, cursor="hand2")
        self.btn_nav_home.pack(fill="x", pady=(20, 0))
        self.btn_nav_home.bind("<Button-1>", lambda e: self.switch_to_homepage())
        self.btn_nav_home.bind("<Enter>", lambda e: self.btn_nav_home.config(bg="#3f4147"))
        self.btn_nav_home.bind("<Leave>", lambda e: self.btn_nav_home.config(bg=BG_SIDEBAR))
        
        self.btn_nav_dupes = tk.Label(self.sidebar, text="📄 Duplicates", font=FONT_MAIN, bg=BG_SIDEBAR, fg=FG_TEXT, 
                                      anchor="w", padx=20, pady=10, cursor="hand2")
        self.btn_nav_dupes.pack(fill="x")
        self.btn_nav_dupes.bind("<Button-1>", lambda e: self.switch_to_duplicates())
        self.btn_nav_dupes.bind("<Enter>", lambda e: self.btn_nav_dupes.config(bg="#3f4147"))
        self.btn_nav_dupes.bind("<Leave>", lambda e: self.btn_nav_dupes.config(bg=BG_SIDEBAR))

        # Content Area Containers
        self.content_area = tk.Frame(self.body_frame, bg=BG_MAIN)
        self.content_area.pack(side="left", fill="both", expand=True, padx=30, pady=20)
        
        self.frame_homepage = tk.Frame(self.content_area, bg=BG_MAIN)
        self.frame_duplicates = tk.Frame(self.content_area, bg=BG_MAIN)
        self.frame_search = tk.Frame(self.content_area, bg=BG_MAIN)
        
        self.build_homepage()
        self.build_duplicates_view()
        self.build_search_view()

    def build_homepage(self):
        # Status
        self.lbl_main_status = tk.Label(self.frame_homepage, text="Checked", font=FONT_LARGE, bg=BG_MAIN, fg=FG_TEXT)
        self.lbl_main_status.pack(anchor="w", pady=(0, 20))
        
        # Grid layout for content
        grid_frame = tk.Frame(self.frame_homepage, bg=BG_MAIN)
        grid_frame.pack(fill="both", expand=True)
        grid_frame.columnconfigure(0, weight=2)
        grid_frame.columnconfigure(1, weight=1)
        
        # Left Column: Monitored Folders
        folders_frame = tk.Frame(grid_frame, bg=BG_MAIN)
        folders_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 20))
        
        tk.Label(folders_frame, text="Monitored Folders", font=FONT_MAIN, bg=BG_MAIN, fg=FG_TEXT_MUTED).pack(anchor="w", pady=(0, 10))
        
        self.tree_folders = ttk.Treeview(folders_frame, columns=("Path",), show="headings", height=15)
        self.tree_folders.heading("Path", text="Path")
        self.tree_folders.column("Path", width=400)
        self.tree_folders.bind("<Double-1>", self.open_folder_from_tree)
        self.tree_folders.pack(fill="both", expand=True)
        
        # Right Column: Quick Access & Controls
        quick_frame = tk.Frame(grid_frame, bg=BG_MAIN)
        quick_frame.grid(row=0, column=1, sticky="n")
        
        tk.Label(quick_frame, text="Quick Access", font=FONT_MAIN, bg=BG_MAIN, fg=FG_TEXT_MUTED).pack(anchor="w", pady=(0, 10))
        
        # Custom label as button for better styling
        btn_add = tk.Label(quick_frame, text="➕ Add monitored folders", font=FONT_MAIN, bg=ACCENT_BLUE, fg="black", 
                           padx=15, pady=8, cursor="hand2")
        btn_add.pack(fill="x", pady=(0, 10))
        btn_add.bind("<Button-1>", lambda e: self.add_folder())
        btn_add.bind("<Enter>", lambda e: btn_add.config(bg="#a6c6f9"))
        btn_add.bind("<Leave>", lambda e: btn_add.config(bg=ACCENT_BLUE))
        
        lbl_link = tk.Label(quick_frame, text="🔗 GitHub Releases", font=FONT_MAIN, bg=BG_MAIN, fg=ACCENT_BLUE, cursor="hand2")
        lbl_link.pack(anchor="w", pady=(0, 20))
        lbl_link.bind("<Button-1>", lambda e: webbrowser.open("https://github.com/Mastkasin/DuplicateDeleter/releases"))
        
        tk.Label(quick_frame, text="Actions", font=FONT_MAIN, bg=BG_MAIN, fg=FG_TEXT_MUTED).pack(anchor="w", pady=(20, 10))
        
        btn_check = tk.Label(quick_frame, text="🔍 Check Now (Manual)", font=FONT_MAIN, bg="#3f4147", fg=FG_TEXT, 
                             padx=15, pady=8, cursor="hand2")
        btn_check.pack(fill="x", pady=(0, 10))
        btn_check.bind("<Button-1>", lambda e: self.manual_check())
        btn_check.bind("<Enter>", lambda e: btn_check.config(bg="#4c4e54"))
        btn_check.bind("<Leave>", lambda e: btn_check.config(bg="#3f4147"))
        
        btn_rm = tk.Label(quick_frame, text="🗑️ Remove Selected Folder", font=FONT_MAIN, bg="#3f4147", fg="#ff6b6b", 
                          padx=15, pady=8, cursor="hand2")
        btn_rm.pack(fill="x")
        btn_rm.bind("<Button-1>", lambda e: self.delete_folder())
        btn_rm.bind("<Enter>", lambda e: btn_rm.config(bg="#4c4e54"))
        btn_rm.bind("<Leave>", lambda e: btn_rm.config(bg="#3f4147"))

    def build_duplicates_view(self):
        tk.Label(self.frame_duplicates, text="History & Logs", font=FONT_LARGE, bg=BG_MAIN, fg=FG_TEXT).pack(anchor="w", pady=(0, 20))
        
        self.tree_dupes = ttk.Treeview(self.frame_duplicates, columns=("Name", "Status", "Location"), show="headings", height=20)
        self.tree_dupes.heading("Name", text="Name")
        self.tree_dupes.heading("Status", text="Status")
        self.tree_dupes.heading("Location", text="Location")
        
        self.tree_dupes.column("Name", width=200)
        self.tree_dupes.column("Status", width=100)
        self.tree_dupes.column("Location", width=450)
        
        self.tree_dupes.tag_configure("DELETED", foreground=ACCENT_GREEN)
        self.tree_dupes.tag_configure("DETECTED", foreground=ACCENT_YELLOW)
        
        self.tree_dupes.bind("<Double-1>", self.open_folder_from_log_tree)
        self.tree_dupes.pack(fill="both", expand=True)

    def build_search_view(self):
        self.lbl_search_title = tk.Label(self.frame_search, text="Search Results", font=FONT_LARGE, bg=BG_MAIN, fg=FG_TEXT)
        self.lbl_search_title.pack(anchor="w", pady=(0, 20))
        
        self.tree_search = ttk.Treeview(self.frame_search, columns=("Name", "Status", "Location"), show="headings", height=20)
        self.tree_search.heading("Name", text="Name")
        self.tree_search.heading("Status", text="Status")
        self.tree_search.heading("Location", text="Location")
        
        self.tree_search.column("Name", width=200)
        self.tree_search.column("Status", width=100)
        self.tree_search.column("Location", width=450)
        
        self.tree_search.tag_configure("DELETED", foreground=ACCENT_GREEN)
        self.tree_search.tag_configure("DETECTED", foreground=ACCENT_YELLOW)
        
        self.tree_search.bind("<Double-1>", self.open_folder_from_log_tree)
        self.tree_search.pack(fill="both", expand=True)

    # ==========================================
    # NAVIGATION
    # ==========================================
    def switch_to_homepage(self):
        self.frame_duplicates.pack_forget()
        self.frame_search.pack_forget()
        self.frame_homepage.pack(fill="both", expand=True)

    def switch_to_duplicates(self):
        self.frame_homepage.pack_forget()
        self.frame_search.pack_forget()
        self.populate_log_tree(self.tree_dupes)
        self.frame_duplicates.pack(fill="both", expand=True)

    def switch_to_search_results(self):
        query = self.search_var.get().lower()
        if query == "search in log" or not query.strip(): return
        
        self.frame_homepage.pack_forget()
        self.frame_duplicates.pack_forget()
        
        self.lbl_search_title.config(text=f"Search Results for: '{query}'")
        self.populate_log_tree(self.tree_search, search_query=query)
        self.frame_search.pack(fill="both", expand=True)

    # ==========================================
    # OS INTERACTIONS
    # ==========================================
    def open_folder_in_os(self, path):
        if not os.path.exists(path): return
        try:
            if platform.system() == "Windows":
                os.startfile(path)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", path])
        except Exception as e:
            logging.error(f"Failed to open folder {path}: {e}")

    def open_folder_from_tree(self, event):
        item = self.tree_folders.selection()
        if item:
            path = self.tree_folders.item(item[0], "values")[0]
            self.open_folder_in_os(path)

    def open_folder_from_log_tree(self, event):
        tree = event.widget
        item = tree.selection()
        if item:
            file_path = tree.item(item[0], "values")[2]
            folder_path = os.path.dirname(file_path)
            self.open_folder_in_os(folder_path)

    # ==========================================
    # DUPLICATE LOGIC & MANUAL CHECK WINDOW
    # ==========================================
    def manual_check(self):
        if not self.monitored_folders:
            messagebox.showwarning("No Folders", "Please add at least one folder.")
            return
        
        self.lbl_main_status.config(text="Searching for Duplicates...")
        self.root.update_idletasks()
        
        duplicates_dict = self.perform_scan_dict()
        
        self.lbl_main_status.config(text="Checked")
        
        if not duplicates_dict:
            messagebox.showinfo("Result", "No duplicates found.")
            return
            
        self.show_manual_check_results(duplicates_dict)

    def perform_scan_dict(self):
        seen_hashes = {}
        duplicates_grouped = {}
        
        for folder in self.monitored_folders:
            for root_dir, _, files in os.walk(folder):
                for filename in files:
                    if filename == ".DS_Store": continue
                    filepath = os.path.join(root_dir, filename)
                    
                    hasher = hashlib.md5()
                    try:
                        with open(filepath, 'rb') as f:
                            buf = f.read(65536)
                            while len(buf) > 0:
                                hasher.update(buf)
                                buf = f.read(65536)
                        file_hash = hasher.hexdigest()
                        
                        if file_hash in self.ignored_hashes: continue
                        
                        if file_hash in seen_hashes:
                            if file_hash not in duplicates_grouped:
                                duplicates_grouped[file_hash] = [seen_hashes[file_hash]]
                            duplicates_grouped[file_hash].append(filepath)
                            log_record("DETECTED", filename, filepath)
                        else:
                            seen_hashes[file_hash] = filepath
                    except:
                        pass
        return duplicates_grouped

    def show_manual_check_results(self, duplicates_dict):
        top = tk.Toplevel(self.root)
        top.title("Duplicate Manager")
        top.geometry("800x600")
        top.configure(bg=BG_MAIN)
        
        tk.Label(top, text="Found Duplicates", font=FONT_LARGE, bg=BG_MAIN, fg=FG_TEXT).pack(anchor="w", padx=20, pady=20)
        
        canvas = tk.Canvas(top, bg=BG_MAIN, highlightthickness=0)
        scrollbar = ttk.Scrollbar(top, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas, bg=BG_MAIN)
        
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw", width=750)
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True, padx=20)
        scrollbar.pack(side="right", fill="y")
        
        group_num = 1
        for f_hash, paths in duplicates_dict.items():
            if len(paths) < 2: continue
            
            grp_frame = tk.Frame(scroll_frame, bg=BG_SIDEBAR, pady=10)
            grp_frame.pack(fill="x", pady=10)
            
            names = [f"'{os.path.basename(p)}'" for p in paths]
            title_text = f"{group_num}. {' and '.join(names)}"
            
            header_frame = tk.Frame(grp_frame, bg=BG_SIDEBAR)
            header_frame.pack(fill="x", padx=10)
            
            tk.Label(header_frame, text=title_text, font=FONT_TITLE, bg=BG_SIDEBAR, fg=FG_TEXT, wraplength=600, justify="left").pack(side="left")
            
            # Label acting as a functional button
            btn_merge = tk.Label(header_frame, text="Merge", font=FONT_MAIN, bg=ACCENT_BLUE, fg="black", padx=10, pady=4, cursor="hand2")
            btn_merge.pack(side="right")
            btn_merge.bind("<Button-1>", lambda e, p=paths, frm=grp_frame: self.merge_group(p, frm))
            btn_merge.bind("<Enter>", lambda e, lbl=btn_merge: lbl.config(bg="#a6c6f9"))
            btn_merge.bind("<Leave>", lambda e, lbl=btn_merge: lbl.config(bg=ACCENT_BLUE))
            
            for path in paths:
                file_frame = tk.Frame(grp_frame, bg=BG_MAIN, pady=5)
                file_frame.pack(fill="x", padx=10, pady=2)
                
                name = os.path.basename(path)
                tk.Label(file_frame, text=name, bg=BG_MAIN, fg=FG_TEXT, width=25, anchor="w").pack(side="left", padx=5)
                
                lbl_loc = tk.Label(file_frame, text=path, bg=BG_MAIN, fg=ACCENT_BLUE, cursor="hand2", anchor="w")
                lbl_loc.pack(side="left", fill="x", expand=True, padx=5)
                lbl_loc.bind("<Double-1>", lambda e, p=path: self.open_folder_in_os(os.path.dirname(p)))
                
                # Label acting as a functional button
                btn_merge_here = tk.Label(file_frame, text="Merge Here", font=FONT_MAIN, bg="#3f4147", fg=FG_TEXT, padx=10, pady=2, cursor="hand2")
                btn_merge_here.pack(side="right", padx=5)
                btn_merge_here.bind("<Button-1>", lambda e, p=path, f=file_frame: self.merge_single(p, f))
                btn_merge_here.bind("<Enter>", lambda e, lbl=btn_merge_here: lbl.config(bg="#4c4e54"))
                btn_merge_here.bind("<Leave>", lambda e, lbl=btn_merge_here: lbl.config(bg="#3f4147"))
                
            group_num += 1

    def merge_single(self, filepath, ui_frame):
        try:
            send2trash(filepath)
            log_record("DELETED", os.path.basename(filepath), filepath)
            ui_frame.destroy()
        except Exception as e:
            logging.error(f"Error merging single file: {e}")

    def merge_group(self, paths, ui_frame):
        try:
            for path in paths[1:]:
                send2trash(path)
                log_record("DELETED", os.path.basename(path), path)
            ui_frame.destroy()
        except Exception as e:
            logging.error(f"Error merging group: {e}")

    # ==========================================
    # LOG READING
    # ==========================================
    def populate_log_tree(self, tree, search_query=""):
        for row in tree.get_children():
            tree.delete(row)
            
        if not os.path.exists(log_file_path): return
        
        records = []
        with open(log_file_path, "r", encoding="utf-8") as f:
            for line in f:
                if "RECORD|" in line:
                    parts = line.strip().split("RECORD|")[1].split("|")
                    if len(parts) >= 3:
                        status, name, loc = parts[0], parts[1], parts[2]
                        
                        if search_query:
                            if search_query not in name.lower() and search_query not in loc.lower():
                                continue
                        
                        # Translate status for display in UI
                        status_disp = "Deleted" if status == "DELETED" else "Detected"
                        records.append((name, status_disp, loc, status))
                        
        # Insert in reverse order (newest first)
        for r in reversed(records):
            tree.insert("", "end", values=(r[0], r[1], r[2]), tags=(r[3],))

    # ==========================================
    # STARTUP & CONFIGURATION FUNCTIONS
    # ==========================================
    def add_folder(self):
        path = filedialog.askdirectory()
        if path and path not in self.monitored_folders:
            self.monitored_folders.append(path)
            self.update_folders_ui()
            self.save_config()

    def delete_folder(self):
        sel = self.tree_folders.selection()
        if sel:
            path = self.tree_folders.item(sel[0], "values")[0]
            if path in self.monitored_folders:
                self.monitored_folders.remove(path)
                self.update_folders_ui()
                self.save_config()

    def update_folders_ui(self):
        for item in self.tree_folders.get_children():
            self.tree_folders.delete(item)
        for folder in self.monitored_folders:
            self.tree_folders.insert("", "end", values=(folder,))

    def save_config(self):
        data = {
            "monitored_folders": self.monitored_folders,
            "ignored_hashes": list(self.ignored_hashes),
        }
        try:
            with open(config_file_path, 'w') as f: json.dump(data, f)
        except: pass

    def load_config(self):
        if os.path.exists(config_file_path):
            try:
                with open(config_file_path, 'r') as f:
                    data = json.load(f)
                    self.monitored_folders = data.get("monitored_folders", [])
                    self.ignored_hashes = set(data.get("ignored_hashes", []))
                    self.update_folders_ui()
            except: pass

    def enable_system_startup(self):
        """Registers the app to launch automatically on system boot/login."""
        try:
            exe_path = os.path.abspath(sys.argv[0])
            if platform.system() == "Windows":
                import winreg
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
                winreg.SetValueEx(key, "DuplicateDeleter", 0, winreg.REG_SZ, f'"{exe_path}"')
                winreg.CloseKey(key)
            elif platform.system() == "Darwin":
                plist_dir = os.path.expanduser("~/Library/LaunchAgents")
                plist_path = os.path.join(plist_dir, "com.mastkasin.duplicatedeleter.plist")
                plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict><key>Label</key><string>com.mastkasin.duplicatedeleter</string><key>ProgramArguments</key><array><string>{exe_path}</string></array><key>RunAtLoad</key><true/></dict>
</plist>"""
                os.makedirs(plist_dir, exist_ok=True)
                with open(plist_path, "w") as f: f.write(plist_content)
        except: pass

    def setup_tray_icon(self):
        """Initializes the background tray icon based on the OS."""
        if platform.system() == "Darwin":
            if self.tray_process is None or not self.tray_process.is_alive():
                self.tray_process = multiprocessing.Process(target=run_mac_tray_process, args=(self.child_conn,), daemon=True)
                self.tray_process.start()
        else:
            try:
                image = Image.new('RGB', (64, 64), color=(147, 51, 234))
                draw = ImageDraw.Draw(image)
                draw.ellipse((16, 16, 48, 48), fill=(255, 255, 255))
                menu = pystray.Menu(
                    item('Open Dashboard', lambda i, it: self.root.after(0, self.show_window)),
                    pystray.Menu.SEPARATOR,
                    item('Auto-Cull Enabled (Click to Quit)', lambda i, it: self.root.after(0, self.quit_app))
                )
                self.tray_icon = pystray.Icon("DuplicateDeleter", image, "DuplicateDeleter", menu, action=lambda icon: self.root.after(0, self.show_window))
                threading.Thread(target=self.tray_icon.run, daemon=True).start()
            except: pass

    def poll_queue(self):
        """Listens to signals from the macOS menu bar icon."""
        try:
            while self.parent_conn.poll():
                msg = self.parent_conn.recv()
                if msg == "TOGGLE_DASHBOARD":
                    if self.root.state() == 'normal' and self.root.winfo_viewable(): self.hide_window()
                    else: self.show_window()
                elif msg == "FORCE_FOREGROUND": self.show_window()
                elif msg == "DISABLE_AUTOCULL_QUIT" or msg == "QUIT_APP": self.quit_app()
        except: pass
        self.root.after(100, self.poll_queue)

    def hide_window(self): self.root.withdraw()
    
    def show_window(self):
        try:
            if self.root.state() != 'normal': self.root.deiconify()
            self.root.focus_force()
        except: pass

    def quit_app(self):
        """Gracefully terminates all processes and icons without memory leaks."""
        try:
            if self.tray_icon:
                self.tray_icon.visible = False
                self.tray_icon.stop()
        except: pass
        try:
            if self.tray_process and self.tray_process.is_alive():
                self.tray_process.terminate()
                self.tray_process.join()
        except: pass
        try:
            self.parent_conn.close()
            self.child_conn.close()
        except: pass
        self.root.destroy()
        sys.exit(0)

    # Legacy Auto-Cull methods retained for future logic compatibility
    def apply_frequency(self): pass
    def schedule_auto_cull(self): pass
    def run_auto_cull(self): pass

if __name__ == "__main__":
    multiprocessing.freeze_support()
    root = tk.Tk()
    app = DuplicateDeleterApp(root)
    root.mainloop()
