"""Native-window launcher for the Sample Scout UI recreation.

Mirrors the original's actual architecture — a Rust/Tauri backend
serving a bundled webview frontend inside a native OS window — by using
``pywebview`` to host the Flask app (``webapp/server.py``) in a real
native window instead of a browser tab.

    python desktop.py

Falls back to printing the local URL if pywebview/its native webview
backend isn't available on this machine (e.g. headless CI); use
``python -m webapp.server`` plus a regular browser tab in that case.
"""
from __future__ import annotations

import socket
import threading

from webapp.server import app


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> None:
    port = _free_port()
    thread = threading.Thread(
        target=lambda: app.run(port=port, debug=False, use_reloader=False),
        daemon=True,
    )
    thread.start()

    url = f"http://127.0.0.1:{port}/"
    try:
        import webview
    except ImportError:
        print(f"pywebview not installed. Open this URL in a browser: {url}")
        thread.join()
        return

    webview.create_window("Sample Scout", url, width=1300, height=840, min_size=(900, 600))
    webview.start()


if __name__ == "__main__":
    main()
