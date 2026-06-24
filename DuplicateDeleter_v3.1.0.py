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
from send2trash import send2trash

# Background Tray Icon libraries
import pystray
from pystray import MenuItem as item
from PIL import Image, ImageDraw

# ==========================================
# CONFIGURATION & PATHS
# ==========================================
VERSION = "v3.1.0"
LOG_FILENAME = "DuplicateDeleter.log"
CONFIG_FILENAME = "DuplicateDeleter_config.json"

home_dir = os.path.expanduser("~")
downloads_dir = os.path.join(home_dir, "Downloads")
if not os.path.exists(downloads_dir):
    downloads_dir = home_dir

log_file_path = os.path.join(downloads_dir, LOG_FILENAME)
config_file_path = os.path.join(home_dir, CONFIG_FILENAME)

# Initialize log file
logging.basicConfig(
    filename=log_file_path, 
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s'
)

logging.info(f"--- Started DuplicateDeleter {VERSION} Background Daemon ---")

# ==========================================
# ISOLATED MACOS TRAY PROCESS
# ==========================================
def run_mac_tray_process(conn):
    """Runs completely isolated on macOS using a Pipe to prevent AppKit crashes."""
    def on_open(icon, item):
        conn.send("TOGGLE_DASHBOARD")
        
    def on_toggle_autocull(icon, item):
        conn.send("DISABLE_AUTOCULL_QUIT")

    def on_icon_click(icon):
        conn.send("FORCE_FOREGROUND")

    # Create tray icon image (purple with white dot)
    image = Image.new('RGB', (64, 64), color=(147, 51, 234))
    draw = ImageDraw.Draw(image)
    draw.ellipse((16, 16, 48, 48), fill=(255, 255, 255))
    
    # Menu without the redundant quit button
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
        self.root.geometry("550x700")
        
        # Intercept window close button to hide instead of quit
        self.root.protocol('WM_DELETE_WINDOW', self.hide_window)
        
        self.monitored_folders = []
        self.duplicates_found = [] 
        self.ignored_hashes = set() 
        
        self.auto_cull_ms = 0 
        self.saved_auto_cull_ms = 0 
        self.after_id = None 
        
        # Windows tray variables
        self.tray_icon = None
        
        # Safe Pipe connection for macOS communication (no semaphores)
        self.parent_conn, self.child_conn = multiprocessing.Pipe(duplex=False)
        self.tray_process = None
        
        self.setup_ui()
        self.load_config()
        self.enable_system_startup() 
        
        # Always start the background tray icon
        self.setup_tray_icon()
            
        # Poll for incoming signals from the tray icon
        self.poll_queue()

    def setup_ui(self):
        # --- Listbox for Folders ---
        tk.Label(self.root, text="Monitored Folders:", font=("Arial", 14, "bold")).pack(pady=(15, 5))
        
        self.listbox = tk.Listbox(self.root, width=60, height=8)
        self.listbox.pack(pady=5)
        
        button_frame = tk.Frame(self.root)
        button_frame.pack(pady=5)
        
        tk.Button(button_frame, text="Add Folder", command=self.add_folder).pack(side=tk.LEFT, padx=10)
        tk.Button(button_frame, text="Remove from List", command=self.delete_folder, fg="red").pack(side=tk.LEFT, padx=10)
        
        # --- Auto-Cull Configuration ---
        freq_frame = tk.LabelFrame(self.root, text="Auto-Cull Configuration", padx=10, pady=10)
        freq_frame.pack(pady=15, fill="x", padx=20)
        
        input_frame = tk.Frame(freq_frame)
        input_frame.pack(pady=5)
        
        self.freq_entry = tk.Entry(input_frame, width=8, justify="center")
        self.freq_entry.pack(side=tk.LEFT, padx=5)
        self.freq_entry.insert(0, "0") 
        
        self.unit_var = tk.StringVar()
        self.unit_dropdown = ttk.Combobox(input_frame, textvariable=self.unit_var, state="readonly", width=12)
        self.unit_dropdown['values'] = ("Seconds", "Minutes", "Hours", "Days")
        self.unit_dropdown.current(1) 
        self.unit_dropdown.pack(side=tk.LEFT, padx=5)
        
        tk.Button(input_frame, text="Apply Timer", command=self.apply_frequency).pack(side=tk.LEFT, padx=10)
        
        self.status_label = tk.Label(freq_frame, text="Status: Disabled", fg="gray")
        self.status_label.pack(pady=5)

        tk.Button(self.root, text="Check Now (Manual)", command=self.check_duplicates, font=("Arial", 12), bg="#007AFF").pack(pady=10)
        
        tk.Label(self.root, text="Closing this window keeps the app running safely in the background.", fg="gray", font=("Arial", 9)).pack(pady=15)
        
        tk.Button(self.root, text="Quit DuplicateDeleter", command=self.quit_app, fg="red").pack(side=tk.BOTTOM, pady=20)

    def enable_system_startup(self):
        """Registers the app to launch automatically on system boot/login."""
        try:
            exe_path = os.path.abspath(sys.argv[0])
            if platform.system() == "Windows":
                import winreg
                key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
                winreg.SetValueEx(key, "DuplicateDeleter", 0, winreg.REG_SZ, f'"{exe_path}"')
                winreg.CloseKey(key)
            elif platform.system() == "Darwin":
                plist_dir = os.path.expanduser("~/Library/LaunchAgents")
                plist_path = os.path.join(plist_dir, "com.mastkasin.duplicatedeleter.plist")
                plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.mastkasin.duplicatedeleter</string>
    <key>ProgramArguments</key>
    <array>
        <string>{exe_path}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>"""
                os.makedirs(plist_dir, exist_ok=True)
                with open(plist_path, "w") as f:
                    f.write(plist_content)
        except:
            pass

    def setup_tray_icon(self):
        """Initializes the background tray icon based on the OS."""
        if platform.system() == "Darwin":
            if self.tray_process is None or not self.tray_process.is_alive():
                self.tray_process = multiprocessing.Process(target=run_mac_tray_process, args=(self.child_conn,), daemon=True)
                self.tray_process.start()
        else:
            if self.tray_icon is not None:
                self.tray_icon.visible = True
                return
            try:
                image = self.create_tray_image()
                # Windows menu without the redundant quit button
                menu = pystray.Menu(
                    item('Open Dashboard', self.on_windows_tray_open),
                    pystray.Menu.SEPARATOR,
                    item('Auto-Cull Enabled (Click to Quit)', self.on_windows_tray_autocull)
                )
                self.tray_icon = pystray.Icon("DuplicateDeleter", image, "DuplicateDeleter", menu, action=lambda icon: self.root.after(0, self.show_window))
                threading.Thread(target=self.tray_icon.run, daemon=True).start()
            except:
                pass

    def create_tray_image(self):
        image = Image.new('RGB', (64, 64), color=(147, 51, 234))
        draw = ImageDraw.Draw(image)
        draw.ellipse((16, 16, 48, 48), fill=(255, 255, 255))
        return image

    def poll_queue(self):
        """Listens to signals from the macOS menu bar icon."""
        try:
            while self.parent_conn.poll():
                msg = self.parent_conn.recv()
                if msg == "TOGGLE_DASHBOARD":
                    if self.root.state() == 'normal' and self.root.winfo_viewable():
                        self.hide_window()
                    else:
                        self.show_window()
                elif msg == "FORCE_FOREGROUND":
                    self.show_window()
                elif msg == "DISABLE_AUTOCULL_QUIT":
                    self.quit_app()
                elif msg == "QUIT_APP":
                    self.quit_app()
        except Exception:
            pass
        self.root.after(100, self.poll_queue)

    def on_windows_tray_open(self, icon, item):
        if self.root.state() == 'normal' and self.root.winfo_viewable():
            self.root.after(0, self.hide_window)
        else:
            self.root.after(0, self.show_window)

    def on_windows_tray_autocull(self, icon, item):
        self.root.after(0, self.quit_app)

    def hide_window(self):
        self.root.withdraw()

    def show_window(self):
        try:
            if self.root.state() != 'normal':
                self.root.deiconify()
            self.root.focus_force()
        except:
            pass

    def quit_app(self):
        """Gracefully terminates all processes and icons without memory leaks."""
        try:
            if self.tray_icon:
                self.tray_icon.visible = False
                self.tray_icon.stop()
        except:
            pass
        
        try:
            if self.tray_process and self.tray_process.is_alive():
                self.tray_process.terminate()
                self.tray_process.join()
        except:
            pass
            
        try:
            self.parent_conn.close()
            self.child_conn.close()
        except:
            pass
            
        self.root.destroy()
        sys.exit(0)

    # ==========================================
    # DATA & LOGIC SYSTEM
    # ==========================================
    def save_config(self):
        data = {
            "monitored_folders": self.monitored_folders,
            "ignored_hashes": list(self.ignored_hashes),
            "auto_cull_ms": self.auto_cull_ms,
            "saved_auto_cull_ms": self.saved_auto_cull_ms,
            "unit": self.unit_var.get(),
            "freq_value": self.freq_entry.get()
        }
        try:
            with open(config_file_path, 'w') as config_file:
                json.dump(data, config_file)
        except:
            pass

    def load_config(self):
        if os.path.exists(config_file_path):
            try:
                with open(config_file_path, 'r') as config_file:
                    data = json.load(config_file)
                    self.monitored_folders = data.get("monitored_folders", [])
                    self.ignored_hashes = set(data.get("ignored_hashes", []))
                    self.update_listbox()
                    
                    if "unit" in data: self.unit_var.set(data["unit"])
                    if "freq_value" in data:
                        self.freq_entry.delete(0, tk.END)
                        self.freq_entry.insert(0, data["freq_value"])
                    
                    self.saved_auto_cull_ms = data.get("saved_auto_cull_ms", 0)
                    self.auto_cull_ms = data.get("auto_cull_ms", 0)
                    
                    if self.auto_cull_ms > 0:
                        self.status_label.config(text=f"Status: Service active ({data.get('freq_value')} {data.get('unit')})", fg="green")
                        self.schedule_auto_cull()
            except:
                pass

    def apply_frequency(self):
        try:
            value = float(self.freq_entry.get())
            if value < 0: raise ValueError
        except ValueError:
            messagebox.showerror("Invalid Input", "Please enter a valid positive number.")
            return
            
        unit = self.unit_var.get()
        multiplier = {"Seconds": 1000, "Minutes": 60000, "Hours": 3600000, "Days": 86400000}.get(unit, 60000)
        
        self.auto_cull_ms = int(value * multiplier)
        self.saved_auto_cull_ms = self.auto_cull_ms 
        
        if self.after_id:
            self.root.after_cancel(self.after_id) 
            
        if self.auto_cull_ms > 0:
            disp_val = int(value) if value.is_integer() else value
            self.status_label.config(text=f"Status: Service active ({disp_val} {unit})", fg="green")
            self.schedule_auto_cull()
        else:
            self.status_label.config(text="Status: Disabled", fg="gray")
        self.save_config()

    def schedule_auto_cull(self):
        if self.auto_cull_ms > 0:
            self.after_id = self.root.after(self.auto_cull_ms, self.run_auto_cull)

    def run_auto_cull(self):
        self.perform_scan()
        if self.duplicates_found:
            self.execute_merge() 
        self.schedule_auto_cull() 

    def add_folder(self):
        folder_path = filedialog.askdirectory()
        if folder_path and folder_path not in self.monitored_folders:
            self.monitored_folders.append(folder_path)
            self.update_listbox()
            self.save_config() 

    def delete_folder(self):
        selected_indices = self.listbox.curselection()
        if selected_indices:
            index = selected_indices[0]
            self.monitored_folders.pop(index)
            self.update_listbox()
            self.save_config() 

    def update_listbox(self):
        self.listbox.delete(0, tk.END)
        for folder in self.monitored_folders:
            self.listbox.insert(tk.END, folder)

    def get_file_hash(self, filepath):
        hasher = hashlib.md5()
        try:
            with open(filepath, 'rb') as file:
                buf = file.read(65536)
                while len(buf) > 0:
                    hasher.update(buf)
                    buf = file.read(65536)
            return hasher.hexdigest()
        except:
            return None

    def perform_scan(self):
        self.duplicates_found.clear()
        seen_hashes = {}
        for folder in self.monitored_folders:
            for root_dir, _, files in os.walk(folder):
                for filename in files:
                    if filename == ".DS_Store": continue
                    filepath = os.path.join(root_dir, filename)
                    file_hash = self.get_file_hash(filepath)
                    if file_hash:
                        if file_hash in self.ignored_hashes: continue
                        if file_hash in seen_hashes:
                            self.duplicates_found.append((filepath, file_hash))
                        else:
                            seen_hashes[file_hash] = filepath

    def check_duplicates(self):
        if not self.monitored_folders:
            messagebox.showwarning("No Folders", "Please add at least one folder.")
            return
        self.perform_scan()
        self.show_decision_popup(len(self.duplicates_found))

    def show_decision_popup(self, count):
        if count == 0:
            messagebox.showinfo("Result", "No new duplicates found.")
            return
        popup = tk.Toplevel(self.root)
        popup.title("Action Required")
        popup.geometry("300x150")
        popup.transient(self.root)
        popup.grab_set()
        tk.Label(popup, text=f"Found {count} duplicate(s)!", font=("Arial", 14)).pack(pady=20)
        btn_frame = tk.Frame(popup)
        btn_frame.pack()
        tk.Button(btn_frame, text="Merge", command=lambda: self.execute_merge(popup), width=10).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="Ignore", command=lambda: self.ignore_current_duplicates(popup), width=10).pack(side=tk.LEFT, padx=10)

    def ignore_current_duplicates(self, popup_window):
        for filepath, f_hash in self.duplicates_found:
            self.ignored_hashes.add(f_hash)
        self.save_config() 
        popup_window.destroy()
        messagebox.showinfo("Ignored", "These files will be ignored in future scans.")

    def execute_merge(self, popup_window=None):
        success_count = 0
        for file_path, f_hash in self.duplicates_found:
            try:
                send2trash(file_path)
                success_count += 1
            except Exception as e:
                logging.error(f"Error deleting file: {e}")
        if popup_window:
            popup_window.destroy()
            messagebox.showinfo("Success", f"Moved {success_count} files to trash.")
        self.duplicates_found.clear()

# ==========================================
# EXECUTABLE ENTRY POINT
# ==========================================
if __name__ == "__main__":
    multiprocessing.freeze_support()
    root = tk.Tk()
    app = DuplicateDeleterApp(root)
    root.mainloop()
