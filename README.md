🧹 DuplicateDeleter v3.1.0

The ultimate, lightweight background service to keep your folders clean and organized.

DuplicateDeleter is a highly optimized, cross-platform background application designed to find and remove duplicate files safely. Version 3.1.0 introduces native background daemon execution, automatic system startup, and seamless OS integration.

✨ What's New in v3.1.0?

👻 Always-On Background Daemon: Close the dashboard window, and the app will silently run and monitor your folders in the background (lives in the macOS Dock or Windows System Tray).
⚙️ Auto-Start Service: The app automatically registers itself to launch on system boot (via macOS LaunchAgents or Windows Registry Run keys).
🎚️ Smart Toggle: Control the entire app and its background timers directly from the menu icon.
🛠️ Zero Resource Leaks: Completely re-engineered on macOS using isolated Pipes instead of Semaphores to ensure 100% crash-free background execution.
📂 Multi-Folder Support: Monitor multiple directories simultaneously.

🚀 Installation & Launch

For macOS
Download DuplicateDeleter.zip from the Latest Release.
Unzip and move DuplicateDeleter.app to your Applications folder.
Important (First launch only): Right-click the app and select 'Open' to bypass the macOS unidentified developer warning safely.
Usage: Closing the dashboard window with the 'X' button keeps the app active in your Dock. Click the Dock icon or Menu Bar icon to bring the dashboard back to the front!

For Windows
Download DuplicateDeleter.exe from the Latest Release.
Run the executable. No installation required!
Important: If Windows Defender SmartScreen shows an unidentified developer warning ("Windows protected your PC"), click on "More info" and select "Run anyway" to launch the app safely.
Usage: Closing the window with 'X' minimizes the app to your System Tray (bottom-right of your taskbar, click the ^ arrow if hidden). Right-click the purple icon to toggle Auto-Cull or close the app.

🛠 Features & Safety
Safe Deletion: Files are moved to the Trash/Recycle Bin, never permanently deleted immediately.
100% Offline: No data ever leaves your computer. Your privacy is guaranteed.
Detailed Logs: All actions are saved in the DuplicateDeleter.log file directly in your system's Downloads folder (works across different system languages) for full transparency.

⭐ Support the Project

If DuplicateDeleter helped you save space, please consider starring this repository on GitHub! It helps other people find the tool.
Developed with ❤️ by Mastkasin
