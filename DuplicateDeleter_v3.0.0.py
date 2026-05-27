import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
import hashlib
import logging
import json
import platform
import threading
from send2trash import send2trash

# Background Tray Icon libraries
import pystray
from pystray import MenuItem as item
from PIL import Image, ImageDraw

# ==========================================
# CONFIGURATION
# ==========================================
VERSION = "v3.0.0"
GITHUB_REPO = "Mastkasin/DuplicateDeleter"
LOG_FILENAME = "DuplicateDeleter.log"
CONFIG_FILENAME = "DuplicateDeleter_config.json"

# Setup paths: Log goes to 'Downloads', config stays in Home.
home_dir = os.path.expanduser("~")
downloads_dir = os.path.join(home_dir, "Downloads")

if not os.path.exists(downloads_dir):
    downloads_dir = home_dir

log_file_path = os.path.join(downloads_dir, LOG_FILENAME)
config_file_path = os.path.join(home_dir, CONFIG_FILENAME)

logging.basicConfig(
    filename=log_file_path, 
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s'
)

logging.info(f"--- Started DuplicateDeleter {VERSION} Background Daemon ---")

class DuplicateDeleterApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"DuplicateDeleter {VERSION}")
        self.root.geometry("550x700") # Slightly taller to fit the new Quit button
        
        # Override the close button to hide instead of quit
        self.root.protocol('WM_DELETE_WINDOW', self.hide_window)
        
        # Restore macOS native Dock functionality (clicking Dock icon reopens app)
        if platform.system() == "Darwin":
            self.root.createcommand("::tk::mac::ReopenApplication", self.show_window)
        
        self.monitored_folders = []
        self.duplicates_found = [] 
        self.ignored_hashes = set() 
        
        self.auto_cull_ms = 0 
        self.saved_auto_cull_ms = 0 
        self.after_id = None 
        self.tray_icon = None
        
        self.show_tray_var = tk.BooleanVar(value=True)
        
        self.setup_ui()
        self.load_config() 
        
        if self.show_tray_var.get():
            self.setup_tray_icon()

    def setup_ui(self):
        # --- Listbox for Folders ---
        tk.Label(self.root, text="Monitored Folders:", font=("Arial", 14, "bold")).pack(pady=(15, 5))
        
        self.listbox = tk.Listbox(self.root, width=60, height=8)
        self.listbox.pack(pady=5)
        
        button_frame = tk.Frame(self.root)
        button_frame.pack(pady=5)
        
        tk.Button(button_frame, text="Add Folder", command=self.add_folder).pack(side=tk.LEFT, padx=10)
        tk.Button(button_frame, text="Remove from List", command=self.delete_folder, fg="red").pack(side=tk.LEFT, padx=10)
        
        # --- Auto-Cull Frequency Section ---
        freq_frame = tk.LabelFrame(self.root, text="Auto-Cull Configuration", padx=10, pady=10)
        freq_frame.pack(pady=15, fill="x", padx=20)
        
        input_frame = tk.Frame(freq_frame)
        input_frame.pack(pady=5)
        
        self.freq_entry = tk.Entry(input_frame, width=8, justify="center")
        self.freq_entry.pack(side=tk.LEFT, padx=5)
        self.freq_entry.insert(0, "0") 
        
        self.unit_var = tk.StringVar()
        self.unit_dropdown = ttk.Combobox(input_frame, textvariable=self.unit_var, state="readonly", width=12)
        self.unit_dropdown['values'] = ("Seconds", "Minutes", "Hours", "Days", "Weeks", "Months", "Years")
        self.unit_dropdown.current(1) 
        self.unit_dropdown.pack(side=tk.LEFT, padx=5)
        
        tk.Button(input_frame, text="Apply Timer", command=self.apply_frequency).pack(side=tk.LEFT, padx=10)
        
        self.status_label = tk.Label(freq_frame, text="Status: Disabled", fg="gray")
        self.status_label.pack(pady=5)

        tk.Button(self.root, text="Check Now (Manual)", command=self.check_duplicates, font=("Arial", 12), bg="#007AFF").pack(pady=10)
        
        # --- OS Specific Background Toggles ---
        if platform.system() == "Windows":
            tk.Checkbutton(self.root, text="Show icon in System Tray", variable=self.show_tray_var, command=self.toggle_tray_icon).pack(pady=5)
            tk.Label(self.root, text="Closing this window with 'X' keeps the app running in the background.", fg="gray", font=("Arial", 9)).pack(pady=5)
        else:
            tk.Checkbutton(self.root, text="Keep running in background (Dock) when closed", variable=self.show_tray_var, command=self.toggle_tray_icon).pack(pady=5)
            tk.Label(self.root, text="Closing this window with 'X' keeps the app running in the background.\nClick the app icon in your Dock to reopen this dashboard.", fg="gray", font=("Arial", 9)).pack(pady=5)
        
        # Quit Button to easily exit the app completely
        tk.Button(self.root, text="Quit DuplicateDeleter", command=self.quit_app, fg="red").pack(side=tk.BOTTOM, pady=20)

    # ==========================================
    # BACKGROUND SYSTEM (v3.0.0 OS-Aware)
    # ==========================================
    def toggle_tray_icon(self):
        try:
            if self.show_tray_var.get():
                if platform.system() == "Windows":
                    if self.tray_icon:
                        self.tray_icon.visible = True
                    else:
                        self.setup_tray_icon()
                logging.info("Background mode enabled by user.")
            else:
                if platform.system() == "Windows" and self.tray_icon:
                    self.tray_icon.visible = False
                logging.info("Background mode disabled by user.")
            self.save_config()
        except Exception as e:
            logging.error(f"Error toggling tray icon: {e}")

    def setup_tray_icon(self):
        # macOS crashes if we run pystray in a background thread with Tkinter.
        # We rely on the native macOS Dock instead for Mac users.
        if platform.system() == "Darwin":
            return 
            
        if self.tray_icon is not None:
            self.tray_icon.visible = True
            return 
            
        try:
            image = self.create_tray_image()
            menu = pystray.Menu(
                item('Open Dashboard', self.on_tray_open),
                pystray.Menu.SEPARATOR,
                item('Auto-Cull Enabled', self.on_tray_toggle_autocull, checked=lambda item: self.auto_cull_ms > 0),
                pystray.Menu.SEPARATOR,
                item('Quit DuplicateDeleter', self.on_tray_quit)
            )
            
            self.tray_icon = pystray.Icon("DuplicateDeleter", image, "DuplicateDeleter", menu)
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
        except Exception as e:
            logging.error(f"Error setting up tray icon: {e}")

    def create_tray_image(self):
        image = Image.new('RGB', (64, 64), color=(147, 51, 234))
        draw = ImageDraw.Draw(image)
        draw.ellipse((16, 16, 48, 48), fill=(255, 255, 255))
        return image

    def on_tray_open(self, icon, item):
        self.root.after(0, self.show_window)

    def on_tray_quit(self, icon, item):
        try:
            if self.tray_icon:
                self.tray_icon.visible = False
                self.tray_icon.stop()
        except Exception as e:
            logging.error(f"Error stopping tray icon on quit: {e}")
        self.root.after(0, self.quit_app)

    def on_tray_toggle_autocull(self, icon, item):
        self.root.after(0, self.toggle_autocull_logic)

    def toggle_autocull_logic(self):
        try:
            if self.auto_cull_ms > 0:
                self.saved_auto_cull_ms = self.auto_cull_ms 
                self.auto_cull_ms = 0
                if self.after_id:
                    self.root.after_cancel(self.after_id)
                self.status_label.config(text="Status: Disabled (Paused)", fg="gray")
                logging.info("Auto-Cull paused via background toggle.")
            else:
                if self.saved_auto_cull_ms > 0:
                    self.auto_cull_ms = self.saved_auto_cull_ms
                else:
                    self.auto_cull_ms = 10 * 60 * 1000 
                    self.freq_entry.delete(0, tk.END)
                    self.freq_entry.insert(0, "10")
                    self.unit_var.set("Minutes")
                    
                self.status_label.config(text="Status: Running (Enabled)", fg="green")
                self.schedule_auto_cull()
                logging.info("Auto-Cull resumed via background toggle.")
                
            self.save_config()
        except Exception as e:
            logging.error(f"Error inside toggle_autocull_logic: {e}")

    def hide_window(self):
        if not self.show_tray_var.get():
            if messagebox.askyesno("Quit App", "Background mode is disabled.\n\nClosing this window will completely exit DuplicateDeleter. Do you want to quit?"):
                self.quit_app()
            return
            
        self.root.withdraw()
        logging.info("Dashboard hidden. Running as background daemon.")

    def show_window(self):
        try:
            if self.root.state() != 'normal':
                self.root.deiconify()
            
            self.root.lift()
            self.root.attributes('-topmost', True)
            self.root.after_idle(self.root.attributes, '-topmost', False)
            self.root.focus_force()
        except Exception as e:
            logging.error(f"Error showing window: {e}")

    def quit_app(self):
        logging.info("Shutting down DuplicateDeleter Daemon.")
        try:
            if self.tray_icon:
                self.tray_icon.visible = False
                self.tray_icon.stop()
        except:
            pass
        self.root.destroy()

    # ==========================================
    # SAVE AND LOAD SYSTEM
    # ==========================================
    def save_config(self):
        data = {
            "monitored_folders": self.monitored_folders,
            "ignored_hashes": list(self.ignored_hashes),
            "auto_cull_ms": self.auto_cull_ms,
            "saved_auto_cull_ms": self.saved_auto_cull_ms,
            "unit": self.unit_var.get(),
            "freq_value": self.freq_entry.get(),
            "show_tray_icon": self.show_tray_var.get()
        }
        try:
            with open(config_file_path, 'w') as config_file:
                json.dump(data, config_file)
        except Exception as e:
            logging.error(f"Failed to save config: {e}")

    def load_config(self):
        if os.path.exists(config_file_path):
            try:
                with open(config_file_path, 'r') as config_file:
                    data = json.load(config_file)
                    
                    self.monitored_folders = data.get("monitored_folders", [])
                    self.ignored_hashes = set(data.get("ignored_hashes", []))
                    self.update_listbox()
                    
                    if "unit" in data:
                        self.unit_var.set(data["unit"])
                    if "freq_value" in data:
                        self.freq_entry.delete(0, tk.END)
                        self.freq_entry.insert(0, data["freq_value"])
                        
                    if "show_tray_icon" in data:
                        self.show_tray_var.set(data["show_tray_icon"])
                    
                    self.saved_auto_cull_ms = data.get("saved_auto_cull_ms", 0)
                    self.auto_cull_ms = data.get("auto_cull_ms", 0)
                    
                    if self.auto_cull_ms > 0:
                        disp_val = data.get("freq_value", "0")
                        unit = data.get("unit", "Minutes")
                        self.status_label.config(text=f"Status: Running every {disp_val} {unit}", fg="green")
                        self.schedule_auto_cull()
            except Exception as e:
                logging.error(f"Failed to load config: {e}")

    # ==========================================
    # TIMER & LOGIC
    # ==========================================
    def apply_frequency(self):
        try:
            value = float(self.freq_entry.get())
            if value < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid Input", "Please enter a valid positive number.")
            return
            
        unit = self.unit_var.get()
        multiplier = {"Seconds": 1000, "Minutes": 60000, "Hours": 3600000, "Days": 86400000, "Weeks": 604800000, "Months": 2592000000, "Years": 31536000000}.get(unit, 60000)
        
        self.auto_cull_ms = int(value * multiplier)
        self.saved_auto_cull_ms = self.auto_cull_ms 
        
        if self.after_id:
            self.root.after_cancel(self.after_id) 
            
        if self.auto_cull_ms > 0:
            disp_val = int(value) if value.is_integer() else value
            self.status_label.config(text=f"Status: Running every {disp_val} {unit}", fg="green")
            self.schedule_auto_cull()
        else:
            self.status_label.config(text="Status: Disabled", fg="gray")
            
        self.save_config()

    def schedule_auto_cull(self):
        if self.auto_cull_ms > 0:
            self.after_id = self.root.after(self.auto_cull_ms, self.run_auto_cull)

    def run_auto_cull(self):
        logging.info("Starting scheduled Auto-Cull background scan...")
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
        except Exception:
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
                        if file_hash in self.ignored_hashes:
                            continue
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
                logging.error(f"Error: {e}")
        if popup_window:
            popup_window.destroy()
            messagebox.showinfo("Success", f"Moved {success_count} files to trash.")
        self.duplicates_found.clear()

if __name__ == "__main__":
    root = tk.Tk()
    app = DuplicateDeleterApp(root)
    root.mainloop()
