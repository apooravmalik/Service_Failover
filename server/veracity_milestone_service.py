import logging
import time
import socket
from pywinauto import Application
import psutil
import os

# --- Configuration ---
exe_path = r"C:\Program Files (x86)\i-Comply\Veracity.MilestoneAlarms New with Connected and Disconnected\Veracity.MilestoneAlarms\Veracity.MilestoneAlarms.exe"
target_ip = "172.16.10.56"
target_port = 7777
check_interval = 3600            # Seconds between port checks
window_title_regex = "Viewscape Milestone Alarm Service"
log_file = r"E:\PTZ_logs\milestone_alarm_service.log"
ui_wait_timeout = 60           # Seconds to wait for window/button

# --- Logging setup ---
os.makedirs(os.path.dirname(log_file), exist_ok=True)
logging.basicConfig(
    filename=log_file,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# --- Functions ---
def is_port_open(ip, port, timeout=3):
    """Check if TCP port is reachable."""
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except Exception:
        return False

def is_app_running(exe_name):
    """Check if the EXE is already running."""
    for proc in psutil.process_iter(['name', 'exe']):
        try:
            if proc.info['exe'] and exe_name.lower() in proc.info['exe'].lower():
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False

def start_app_and_activate():
    """Start the EXE and click Activate button if needed."""
    try:
        logging.info(f"Starting application: {exe_path}")
        app = Application(backend="uia").start(exe_path)

        # Wait for main window
        logging.info("Waiting for main window...")
        main_window = app.window(title_re=window_title_regex)
        main_window.wait('exists enabled visible ready', timeout=ui_wait_timeout)

        # Click Activate if button exists
        if 'Activate' in main_window.wrapper_object().children_texts():
            logging.info("Clicking Activate button...")
            main_window['Activate'].click_input()
            logging.info("Activate button clicked successfully!")
        else:
            logging.info("Activate button not found, assuming already activated.")

    except Exception as e:
        logging.error(f"Failed to start app or click Activate: {e}")

# --- Main Loop ---
if __name__ == "__main__":
    logging.info("Milestone Alarm Service monitor started.")

    exe_name_only = os.path.basename(exe_path)

    while True:
        if is_port_open(target_ip, target_port):
            logging.info(f"Port {target_port} on {target_ip} is open.")
            if not is_app_running(exe_name_only):
                logging.info("Application not running. Launching...")
                start_app_and_activate()
            else:
                logging.info("Application already running. Skipping launch.")
        else:
            logging.info(f"Port {target_port} on {target_ip} not open. Retrying in {check_interval}s...")

        time.sleep(check_interval)
