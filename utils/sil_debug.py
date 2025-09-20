import re
import os

def find_last_markers(filename, markers=None):
    """
    Scan a SIL file for markers and find their last occurrences.
    Returns:
        - last_occurrences: dict marker -> (last_index, text)
        - counts: dict marker -> total count
        - total_strings: total number of extracted printable strings
    """
    if markers is None:
        markers = ["Log started", "CreatedNewPTZInstance", "CreateNewPTZIntance"]

    if not os.path.exists(filename):
        print("File not found:", filename)
        return {}, {}, 0

    with open(filename, "rb") as f:
        data = f.read()

    # Extract all printable ASCII substrings
    strings = re.findall(rb"[ -~]{4,}", data)
    texts = [s.decode("utf-8", errors="ignore") for s in strings]

    last_occurrences = {m: (-1, "") for m in markers}
    counts = {m: 0 for m in markers}

    # Scan **from the start** to count, and keep last index
    for idx, text in enumerate(texts):
        for m in markers:
            if m.lower() in text.lower():
                counts[m] += 1
                last_occurrences[m] = (idx, text)

    return last_occurrences, counts, len(texts)


if __name__ == "__main__":
    filename = "proserver_PTZ-2025-05-13-11-39-52.sil"
    print("Scanning:", filename)

    markers = ["Log started", "CreateNewPTZIntance"]  # Focused markers
    last_occurrences, counts, total_strings = find_last_markers(filename, markers)

    print(f"Total extracted strings: {total_strings}\n")

    for m in markers:
        idx, text = last_occurrences[m]
        print(f"Marker '{m}' count: {counts[m]}")
        if idx != -1:
            print(f"Last '{m}' found at index {idx}: ...{text[:100]}")
        else:
            print(f"Marker '{m}' not found")

    # Service health check
    log_idx, _ = last_occurrences.get("Log started", (-1, ""))
    ptz_idx, _ = last_occurrences.get("CreateNewPTZIntance", (-1, ""))

    print("\nService status check:")
    if log_idx == -1:
        print("❌ No 'Log started' found — service may not have started")
    elif ptz_idx == -1 or ptz_idx < log_idx:
        print("⚠️ PTZ instance not created after last log start — service restart may be needed")
    else:
        print("✅ PTZ instance created after last log start — service healthy")
