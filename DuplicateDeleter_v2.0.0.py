import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
import hashlib
import logging
import json
from send2trash import send2trash

# ==========================================
# CONFIGURATION
# ==========================================
VERSION = "v2.0.0"
GITHUB_REPO = "Mastkasin/DuplicateDeleter"
LOG_FILENAME = "DuplicateDeleter.log"
CONFIG_FILENAME = "DuplicateDeleter_config.json"

# Setup paths to the user's home directory (works on Mac and Windows)
home_dir = os.path.expanduser("~")
log_file_path = os.path.join(home_dir, LOG_FILENAME)
config_file_path = os.path.join(home_dir, CONFIG_FILENAME)

# Setup logging
logging.basicConfig(
    filename=log_file_path, 
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s'
)

logging.info(f"--- Started DuplicateDeleter {VERSION} ---")

class DuplicateDeleterApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"DuplicateDeleter {VERSION}")
        self.root.geometry("550x650") # Slightly taller for the new layout
        
        self.monitored_folders = []
        self.duplicates_found = [] 
        self.ignored_hashes = set() 
        
        self.auto_cull_ms = 0 # Stores frequency in milliseconds
        self.after_id = None 
        
        self.setup_ui()
        self.load_config() 

    def setup_ui(self):
        # --- Listbox for Folders ---
        tk.Label(self.root, text="Monitored Folders:", font=("Arial", 14, "bold")).pack(pady=(15, 5))
        
        self.listbox = tk.Listbox(self.root, width=60, height=8)
        self.listbox.pack(pady=5)
        
        # --- Add & Delete Buttons ---
        button_frame = tk.Frame(self.root)
        button_frame.pack(pady=5)
        
        tk.Button(button_frame, text="Add Folder", command=self.add_folder).pack(side=tk.LEFT, padx=10)
        tk.Button(button_frame, text="Remove from List", command=self.delete_folder, fg="red").pack(side=tk.LEFT, padx=10)
        
        # --- Auto-Cull Frequency Section ---
        freq_frame = tk.LabelFrame(self.root, text="Auto-Cull Frequency", padx=10, pady=10)
        freq_frame.pack(pady=15, fill="x", padx=20)
        
        input_frame = tk.Frame(freq_frame)
        input_frame.pack(pady=5)
        
        # Entry box for the number
        self.freq_entry = tk.Entry(input_frame, width=8, justify="center")
        self.freq_entry.pack(side=tk.LEFT, padx=5)
        self.freq_entry.insert(0, "0") # Default is 0
        
        # Dropdown for the unit (Seconds, Minutes, etc.)
        self.unit_var = tk.StringVar()
        self.unit_dropdown = ttk.Combobox(input_frame, textvariable=self.unit_var, state="readonly", width=12)
        self.unit_dropdown['values'] = ("Seconds", "Minutes", "Hours", "Days", "Weeks", "Months", "Years")
        self.unit_dropdown.current(1) # Default to 'Minutes'
        self.unit_dropdown.pack(side=tk.LEFT, padx=5)
        
        # Apply button & Status label
        tk.Button(input_frame, text="Apply Timer", command=self.apply_frequency).pack(side=tk.LEFT, padx=10)
        
        self.status_label = tk.Label(freq_frame, text="Status: Disabled", fg="gray")
        self.status_label.pack(pady=5)

        # --- Manual Check Button ---
        tk.Button(self.root, text="Check Now (Manual)", command=self.check_duplicates, font=("Arial", 12), bg="#007AFF").pack(pady=10)

    # ==========================================
    # SAVE AND LOAD SYSTEM (MEMORY)
    # ==========================================
    def save_config(self):
        data = {
            "monitored_folders": self.monitored_folders,
            "ignored_hashes": list(self.ignored_hashes) 
        }
        try:
            with open(config_file_path, 'w') as config_file:
                json.dump(data, config_file)
            logging.info("Configuration saved successfully.")
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
                    logging.info("Configuration loaded successfully.")
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
        
        # Convert everything to milliseconds
        multiplier = 0
        if unit == "Seconds": multiplier = 1000
        elif unit == "Minutes": multiplier = 60 * 1000
        elif unit == "Hours": multiplier = 60 * 60 * 1000
        elif unit == "Days": multiplier = 24 * 60 * 60 * 1000
        elif unit == "Weeks": multiplier = 7 * 24 * 60 * 60 * 1000
        elif unit == "Months": multiplier = 30 * 24 * 60 * 60 * 1000 # Approx
        elif unit == "Years": multiplier = 365 * 24 * 60 * 60 * 1000 # Approx
        
        self.auto_cull_ms = int(value * multiplier)
        
        if self.after_id:
            self.root.after_cancel(self.after_id) 
            
        if self.auto_cull_ms > 0:
            # Display integer if possible, else float
            disp_val = int(value) if value.is_integer() else value
            self.status_label.config(text=f"Status: Running every {disp_val} {unit}", fg="green")
            logging.info(f"Auto-Cull enabled: Every {disp_val} {unit}.")
            self.schedule_auto_cull()
        else:
            self.status_label.config(text="Status: Disabled", fg="gray")
            logging.info("Auto-Cull disabled by user.")

    def schedule_auto_cull(self):
        if self.auto_cull_ms > 0:
            self.after_id = self.root.after(self.auto_cull_ms, self.run_auto_cull)

    def run_auto_cull(self):
        logging.info("Starting scheduled Auto-Cull scan...")
        self.perform_scan()
        if self.duplicates_found:
            logging.info(f"Auto-Cull: Merging {len(self.duplicates_found)} duplicates automatically.")
            self.execute_merge()
        self.schedule_auto_cull() 

    def add_folder(self):
        folder_path = filedialog.askdirectory()
        if folder_path and folder_path not in self.monitored_folders:
            self.monitored_folders.append(folder_path)
            self.update_listbox()
            self.save_config() 
            logging.info(f"Added folder: {folder_path}")

    def delete_folder(self):
        selected_indices = self.listbox.curselection()
        if selected_indices:
            index = selected_indices[0]
            removed = self.monitored_folders.pop(index)
            self.update_listbox()
            self.save_config() 
            logging.info(f"Removed folder: {removed}")

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
        except Exception as e:
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
        count = len(self.duplicates_found)
        logging.info(f"Manual scan found {count} duplicates.")
        self.show_decision_popup(count)

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
        logging.info(f"User ignored {len(self.duplicates_found)} file contents.")
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
