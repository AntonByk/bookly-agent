from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SERVICES = [
    ("Identity", "services.identity.server:app", int(os.getenv("IDENTITY_PORT", "8001"))),
    ("Commerce", "services.commerce.server:app", int(os.getenv("COMMERCE_PORT", "8002"))),
    ("Knowledge", "services.knowledge.server:app", int(os.getenv("KNOWLEDGE_PORT", "8003"))),
    ("Agent", "app.agent.server:app", int(os.getenv("AGENT_PORT", "8000"))),
]


def healthcheck(port: int, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/health"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.8) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(0.2)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Bookly agent demo locally.")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the browser automatically.")
    args = parser.parse_args()
    processes: list[subprocess.Popen] = []

    def stop_all(*_args):
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, stop_all)
    signal.signal(signal.SIGTERM, stop_all)
    print("Bookly Agent — starting local services...\n")
    for name, app, port in SERVICES:
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", app, "--host", "127.0.0.1", "--port", str(port)], cwd=ROOT, env=os.environ.copy())
        processes.append(process)
        if not healthcheck(port):
            print(f"✗ {name} failed to become healthy on port {port}.")
            stop_all()
        print(f"✓ {name:<10} http://127.0.0.1:{port}")
    url = f"http://127.0.0.1:{SERVICES[-1][2]}"
    print(f"\nBookly is ready: {url}")
    print("Press Ctrl+C to stop all services.")
    if not args.no_browser:
        webbrowser.open(url)
    while True:
        time.sleep(1)


if __name__ == "__main__":
    raise SystemExit(main())
