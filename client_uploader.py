import glob
import os
import time
import json
import urllib.request
import urllib.error

# ── Configuration ────────────────────────────────────────────────
SERVER_URL = "http://localhost:8000/api/session/upload"
POLL_INTERVAL = 5  # seconds
# ─────────────────────────────────────────────────────────────────

_last_size = -1
_last_file = None

def find_newest_csv():
    search_paths = [
        os.path.join(".", "session_*.csv"),
        os.path.join(".", "profiles", "session_*.csv"),
    ]
    all_files = []
    for pattern in search_paths:
        all_files.extend(glob.glob(pattern))

    if not all_files:
        return None

    all_files.sort(key=os.path.getmtime)
    return all_files[-1]

def detect_host(filepath):
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            first_line = f.readline().strip()
        cols = first_line.split(",")
        if len(cols) >= 4:
            tag = cols[3].strip().strip('"').lower()
            if "server" in tag:
                return True
            elif "client" in tag:
                return False
    except Exception:
        pass
    return False

def read_csv_text(filepath):
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return None

def upload(csv_text, is_host):
    payload = json.dumps({
        "csv_content": csv_text,
        "is_host": is_host,
    }).encode("utf-8")

    req = urllib.request.Request(
        SERVER_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status
    except urllib.error.URLError as e:
        return f"Network Error: {e.reason}"
    except Exception as e:
        return f"Error: {e}"

def main():
    global _last_size, _last_file
    
    # These will print immediately upon running the file
    print(f"[*] Uploader Started. Targeting Server: {SERVER_URL}")
    print("[*] Waiting for RVGL session CSV files to appear...")

    while True:
        try:
            filepath = find_newest_csv()

            if filepath is None:
                time.sleep(POLL_INTERVAL)
                continue

            # ── FRESHNESS CHECK ──
            file_age = time.time() - os.path.getmtime(filepath)
            
            # If the file is older than 60 seconds, ignore it!
            if file_age > 60:
                # Only print the ignore message once per stale file to prevent terminal spam
                if filepath != _last_file:
                    print(f"[*] Ignoring stale session file: {filepath} (Last modified {int(file_age)}s ago)")
                    _last_file = filepath
                    _last_size = os.path.getsize(filepath)
                time.sleep(POLL_INTERVAL)
                continue

            if filepath != _last_file:
                print(f"\n[+] Found new active session file: {filepath}")
                _last_file = filepath
                _last_size = -1

            current_size = os.path.getsize(filepath)

            if current_size != _last_size:
                print(f"[*] File size changed ({current_size} bytes). Reading...")
                csv_text = read_csv_text(filepath)
                
                if csv_text:
                    is_host = detect_host(filepath)
                    print(f"[*] Role detected: {'Host' if is_host else 'Client'}")
                    print("[*] Uploading to server...")
                    
                    status = upload(csv_text, is_host)
                    print(f"[*] Server responded with HTTP Status: {status}")
                    
                    _last_size = current_size

        except Exception as e:
            print(f"[!] ERROR: {e}")

        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()