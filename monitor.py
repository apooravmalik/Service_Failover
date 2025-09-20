import time
import subprocess
import psutil
import socket
from datetime import datetime

# =========================
# Configuration
# =========================
PRIMARY_IP = "172.16.10.56"
FALLBACK_IP = "172.16.10.57"
PORT = 7777

SERVICE_NAMES = [
    "Veracity_ptz_monitor",
    "Veracity_sop_monitor",
    "Veracity_PTZ",
    "Veracity_SOP",
    "Veracity.Awiros.AlarmListener",
    "Veracity.OnGuard.DeviceDriver",
    "Veracity.ElfarPIDS.AlarmListner"
]

CHECK_INTERVAL = 10  # seconds
TIMEOUT = 5  # seconds
MAX_STOP_ATTEMPTS = 5
LOG_FILE = "E:\\PTZ_logs\\ServiceMonitor_56.log"

# =========================
# Logging
# =========================
def log(msg):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] INFO: {msg}"
    print(entry)
    with open(LOG_FILE, "a") as f:
        f.write(entry + "\n")

def warn(msg):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] WARNING: {msg}"
    print(entry)
    with open(LOG_FILE, "a") as f:
        f.write(entry + "\n")

# =========================
# Network check
# =========================
def test_connection(ip, port, timeout):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except:
        return False

# =========================
# Kill process tree
# =========================
def kill_process_tree(proc):
    try:
        children = proc.children(recursive=True)
        for child in children:
            child.kill()
        proc.kill()
        log(f"Killed process tree: {proc.name()} (PID {proc.pid})")
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

# =========================
# Stop Service
# =========================
def stop_service(svc, primary_up):
    if svc == "Veracity.ElfarPIDS.AlarmListner" and primary_up:
        log(f"Ignoring {svc} because PRIMARY {PRIMARY_IP}:{PORT} is UP")
        return

    stopped = False
    for attempt in range(1, MAX_STOP_ATTEMPTS + 1):
        try:
            subprocess.run(["sc", "stop", svc], check=True, capture_output=True, text=True, timeout=5)
            log(f"Stopped service: {svc}")
            stopped = True
            break
        except subprocess.CalledProcessError:
            time.sleep(1)

    if not stopped:
        warn(f"Failed to stop {svc} after {MAX_STOP_ATTEMPTS} attempts, attempting to kill process tree")

    # Kill process tree if service still running
    for proc in psutil.process_iter(['pid', 'name', 'exe', 'cmdline']):
        try:
            if svc.lower() in str(proc.info['name']).lower() or \
               (proc.info['exe'] and svc.lower() in str(proc.info['exe']).lower()) or \
               (proc.info['cmdline'] and any(svc.lower() in str(x).lower() for x in proc.info['cmdline'])):
                kill_process_tree(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

# =========================
# Start Service
# =========================
def start_service(svc):
    try:
        subprocess.run(["sc", "start", svc], check=True, capture_output=True, text=True, timeout=5)
        log(f"Started service: {svc}")
    except subprocess.CalledProcessError as e:
        warn(f"Failed to start {svc}: {e}")

# =========================
# Main Loop
# =========================
def monitor_services():
    log("=== Service Monitor Starting ===")
    log(f"Primary: {PRIMARY_IP}:{PORT} | Fallback: {FALLBACK_IP}:{PORT}")
    log("Behavior: STOP services if fallback UP or primary down; START only if primary UP and fallback down")
    log(f"Services: {', '.join(SERVICE_NAMES)}")
    log(f"Check interval: {CHECK_INTERVAL}s | Timeout: {TIMEOUT}s")
    log("===============================")

    services_started = False

    while True:
        primary_up = test_connection(PRIMARY_IP, PORT, TIMEOUT)
        fallback_up = test_connection(FALLBACK_IP, PORT, TIMEOUT)

        log(f"DEBUG: Primary UP={primary_up}, Fallback UP={fallback_up}")

        if primary_up and not fallback_up:
            if not services_started:
                log("*** CONDITIONS MET: PRIMARY UP & FALLBACK DOWN - starting services ***")
                for svc in SERVICE_NAMES:
                    start_service(svc)
                services_started = True
        else:
            # Stop all services if fallback is up or primary down
            log("*** STOPPING services due to connection conditions ***")
            for svc in SERVICE_NAMES:
                stop_service(svc, primary_up)
            services_started = False

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    monitor_services()
