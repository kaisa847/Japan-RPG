"""Start the Visual Novel Engine development server.

Usage:
    python run.py              # auto-reload on code changes
    python run.py --no-reload  # without auto-reload
"""

import sys
import subprocess
import time
from pathlib import Path

PORT = 8000
HOST = "0.0.0.0"
PROJECT_ROOT = Path(__file__).parent
WATCH_DIRS = [PROJECT_ROOT / "backend", PROJECT_ROOT / "frontend"]
WATCH_EXTENSIONS = {".py", ".js", ".css", ".html"}


def start_server():
    """Start uvicorn without --reload (works reliably on Windows Store Python)."""
    return subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "backend.main:app",
            "--host", HOST,
            "--port", str(PORT),
        ],
        cwd=str(PROJECT_ROOT),
    )


def watch_and_reload():
    """Watch source files and restart the server on changes."""
    try:
        from watchfiles import watch
    except ImportError:
        print("[run.py] watchfiles not installed — running without auto-reload.")
        print(f"[run.py] Server: http://{HOST}:{PORT}")
        proc = start_server()
        proc.wait()
        return

    print(f"[run.py] Starting server on http://{HOST}:{PORT} with auto-reload...")
    print(f"[run.py] Watching: {', '.join(str(d) for d in WATCH_DIRS)}")

    proc = start_server()

    try:
        for changes in watch(*WATCH_DIRS):
            # Filter to only relevant file extensions
            relevant = [
                (change_type, path) for change_type, path in changes
                if Path(path).suffix in WATCH_EXTENSIONS
            ]
            if not relevant:
                continue

            names = [Path(p).name for _, p in relevant]
            print(f"[run.py] Detected changes: {', '.join(names)} — restarting...")

            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

            time.sleep(0.3)
            proc = start_server()
    except KeyboardInterrupt:
        print("\n[run.py] Shutting down...")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def run_simple():
    """Run without reload."""
    print(f"[run.py] Starting server on http://{HOST}:{PORT} (no auto-reload)")
    proc = start_server()
    try:
        proc.wait()
    except KeyboardInterrupt:
        print("\n[run.py] Shutting down...")
        proc.terminate()


if __name__ == "__main__":
    if "--no-reload" in sys.argv:
        run_simple()
    else:
        watch_and_reload()
