import requests
import time
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

running = False
SPREADSHEET_ID = ""
SHEET_NAME = ""
LOOP_INTERVAL = 30
SAVE_PATH = ""


def download_google_sheet():
    """Downloads Google Sheet as CSV and saves it locally."""
    if not (SPREADSHEET_ID and SHEET_NAME):
        update_status("[❌] Please enter valid Google Sheet ID and Sheet Name.")
        return

    csv_url = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/gviz/tq?tqx=out:csv&sheet={SHEET_NAME}"

    try:
        response = requests.get(csv_url)
        if response.status_code == 200:
            filename = filename_entry.get().strip()
            if not filename:
                filename = "downloaded_google_sheet"
            csv_filename = f"{filename}.csv"

            save_location = SAVE_PATH if SAVE_PATH else "."
            full_path = f"{save_location}/{csv_filename}"

            with open(full_path, "wb") as file:
                file.write(response.content)

            update_status(f"[✅] Google Sheet saved as: {full_path}")
        else:
            update_status("[❌] Failed to download. Check Sheet ID and sharing settings.")
    except Exception as e:
        update_status(f"[❌] Error: {e}")


def start_loop():
    """Starts the download process with or without looping."""
    global SPREADSHEET_ID, SHEET_NAME, LOOP_INTERVAL, running

    SPREADSHEET_ID = sheet_id_entry.get().strip()
    SHEET_NAME = sheet_name_entry.get().strip()

    try:
        LOOP_INTERVAL = int(loop_time_entry.get().strip())
        if LOOP_INTERVAL < 1:
            messagebox.showerror("Error", "Loop time must be at least 1 second.")
            return
    except ValueError:
        messagebox.showerror("Error", "Invalid loop time. Enter a number.")
        return

    if not (SPREADSHEET_ID and SHEET_NAME):
        messagebox.showerror("Error", "Please enter both Google Sheet ID and Sheet Name.")
        return

    if not running:
        running = True
        update_status("[🔄] Download started...")
        threading.Thread(target=run_loop, daemon=True).start()
    else:
        update_status("[⚠️] Already running!")


def run_loop():
    """Runs the download process, either once or in a loop."""
    download_google_sheet()

    if loop_var.get() == 1:
        update_status(f"[🔁] Looping every {LOOP_INTERVAL} seconds...")
        while running:
            time.sleep(LOOP_INTERVAL)
            if running:
                download_google_sheet()
    else:
        update_status("[✅] Download completed. Loop is OFF.")
        stop_loop()


def stop_loop():
    """Stops the loop."""
    global running
    running = False
    update_status("[⏹️] Stopped.")


def browse_location():
    """Opens file dialog to select folder for saving CSV."""
    global SAVE_PATH
    SAVE_PATH = filedialog.askdirectory()
    if SAVE_PATH:
        location_label.config(text=f"Save Location: {SAVE_PATH}")


def update_status(message):
    """Updates the status label in the GUI."""
    status_label.config(text=message)
    print(message)


# --- GUI setup ---
root = tk.Tk()
root.title("Google Sheet Auto-Downloader")
root.geometry("550x400")

tk.Label(root, text="Google Sheet ID:").pack(pady=5)
sheet_id_entry = tk.Entry(root, width=50)
sheet_id_entry.pack(pady=5)

tk.Label(root, text="Sheet Name:").pack(pady=5)
sheet_name_entry = tk.Entry(root, width=50)
sheet_name_entry.pack(pady=5)

tk.Label(root, text="Save as Filename (without .csv):").pack(pady=5)
filename_entry = tk.Entry(root, width=30)
filename_entry.insert(0, "downloaded_google_sheet")
filename_entry.pack(pady=5)

browse_button = tk.Button(root, text="Browse Save Location", command=browse_location, bg="gray", fg="white")
browse_button.pack(pady=5)

location_label = tk.Label(root, text="Save Location: Default (current folder)")
location_label.pack(pady=5)

loop_var = tk.IntVar()
loop_checkbox = tk.Checkbutton(root, text="Enable Looping", variable=loop_var)
loop_checkbox.pack(pady=5)

tk.Label(root, text="Loop Time (seconds):").pack(pady=5)
loop_time_entry = tk.Entry(root, width=10)
loop_time_entry.insert(0, "30")
loop_time_entry.pack(pady=5)

start_button = tk.Button(root, text="Start Download", command=start_loop, bg="green", fg="white")
start_button.pack(pady=10)

stop_button = tk.Button(root, text="Stop Download", command=stop_loop, bg="red", fg="white")
stop_button.pack(pady=5)

status_label = tk.Label(root, text="[ℹ️] Enter details and start.", fg="blue")
status_label.pack(pady=10)

root.mainloop()
