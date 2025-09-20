import sys
import os
import re
import logging

# ---------------------- FIX PYTHON PATH ----------------------
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config.config_loader import ConfigLoader

logger = logging.getLogger(__name__)

# ---------------------- CONFIG LOADER INSTANCE ----------------------
# Set full path to config.yaml in the config folder
config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'config', 'config.yaml'))
config_loader = ConfigLoader(config_path)
config_loader.load_config()  # Load config.yaml at startup

# ---------------------- LOG FILE READING ----------------------
def read_log_file_lines(file_path: str, encoding: str = 'utf-8') -> list[str]:
    if not os.path.exists(file_path):
        return []
    with open(file_path, 'r', encoding=encoding, errors='ignore') as f:
        return [line.rstrip('\r\n') for line in f.readlines()]

# ---------------------- PTZ SIL / LOG SCAN ----------------------
def find_last_ptz_markers(file_path: str, markers=None):
    """Scan a SIL/text file and find last occurrence of PTZ markers"""
    if markers is None:
        markers = ["Log started", "CreateNewPTZIntance"]
    
    if not os.path.exists(file_path):
        print("❌ File not found:", file_path)
        return {}, {}, 0

    with open(file_path, "rb") as f:
        data = f.read()
    
    # Extract printable ASCII substrings
    strings = re.findall(rb"[ -~]{4,}", data)
    texts = [s.decode("utf-8", errors="ignore") for s in strings]
    
    last_occurrences = {m: (-1, "") for m in markers}
    counts = {m: 0 for m in markers}
    
    for idx, text in enumerate(texts):
        for m in markers:
            if m.lower() in text.lower():
                counts[m] += 1
                last_occurrences[m] = (idx, text)
    
    return last_occurrences, counts, len(texts)

# ---------------------- PTZ SERVICE TEST ----------------------
def test_ptz_service(service_name="Veracity_PTZ"):
    """Test PTZ SIL/log file according to config.yaml via ConfigLoader"""
    service_config = config_loader.get_service_config(service_name)
    if not service_config:
        print(f"❌ Service config '{service_name}' not found")
        return False
    
    file_path = service_config.log_path
    print(f"\nScanning: {file_path}")
    
    last_occurrences, counts, total_strings = find_last_ptz_markers(file_path)
    print(f"\nTotal strings extracted: {total_strings}\n")
    
    for marker in last_occurrences:
        idx, text = last_occurrences[marker]
        print(f"Marker '{marker}' found {counts[marker]} times")
        if idx != -1:
            print(f"  Last occurrence at index {idx}: ...{text[:100]}")
        else:
            print("  Not found")
    
    log_idx, _ = last_occurrences.get("Log started", (-1, ""))
    ptz_idx, _ = last_occurrences.get("CreateNewPTZIntance", (-1, ""))
    
    print("\nService status check:")
    if log_idx == -1:
        print("❌ 'Log started' not found — service may not have started")
        return False
    elif ptz_idx == -1 or ptz_idx < log_idx:
        print("⚠️ PTZ instance not created after last log start — service restart may be needed")
        return False
    else:
        print("✅ PTZ instance created after last log start — service healthy")
        return True

# ---------------------- MAIN ----------------------
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        service_name = sys.argv[1]
        test_ptz_service(service_name)
    else:
        test_ptz_service("Veracity_PTZ")
