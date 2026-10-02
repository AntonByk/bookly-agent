from __future__ import annotations

import argparse
import importlib.util
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def dependency_check() -> list[str]:
    required = ("uvicorn", "fastapi", "httpx", "openai", "pydantic_settings", "dotenv")
    return [name for name in required if importlib.util.find_spec(name) is None]


def build_services() -> list[tuple[str, str, int]]:
    return [
        ("Identity", "services.identity.server:app", int(os.getenv("IDENTITY_PORT", "8001"))),
        ("Commerce", "services.commerce.server:app", int(os.getenv("COMMERCE_PORT", "8002"))),
        ("Knowledge", "services.knowledge.server:app", int(os.getenv("KNOWLEDGE_PORT", "8003"))),
        ("Agent", "app.agent.server:app", int(os.getenv("AGENT_PORT", "8000"))),
    ]


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex(("127.0.0.1", port)) == 0


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

    missing = dependency_check()
    if missing:
        print(
            "Bookly cannot start because the current Python interpreter is missing: "
            + ", ".join(missing)
        )
        print(f"Interpreter: {sys.executable}")
        print("Activate the project virtual environment or run: .venv/bin/python run.py")
        print("If needed, install dependencies with: .venv/bin/pip install -r requirements.txt")
        return 2

    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    services = build_services()

    occupied = [(name, port) for name, _app, port in services if port_in_use(port)]
    if occupied:
        rendered = ", ".join(f"{name} ({port})" for name, port in occupied)
        print(f"Bookly cannot start because these local ports are already in use: {rendered}")
        print("Stop the previous Bookly process first, or configure different ports in .env.")
        return 2

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

    print("Bookly Agent - starting local services...\n")
    for name, app, port in services:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                app,
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=ROOT,
            env=os.environ.copy(),
        )
        processes.append(process)

        # If uvicorn exits immediately, do not accidentally health-check a stale process.
        time.sleep(0.15)
        if process.poll() is not None or not healthcheck(port):
            print(f"x {name} failed to become healthy on port {port}.")
            stop_all()
        print(f"ok {name:<10} http://127.0.0.1:{port}")

    url = f"http://127.0.0.1:{services[-1][2]}"
    print(f"\nBookly is ready: {url}")
    print("Press Ctrl+C to stop all services.")
    if not args.no_browser:
        webbrowser.open(url)

    while True:
        time.sleep(1)


if __name__ == "__main__":
    raise SystemExit(main())
