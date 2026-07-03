from __future__ import annotations

import atexit
from pathlib import Path
import sys
import threading
import time
import webbrowser


def resolve_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parents[1]


ROOT = resolve_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
APP_DIR = ROOT / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from server import create_server  # noqa: E402


def start_local_server() -> tuple[object, str]:
    server = create_server(host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    atexit.register(server.shutdown)
    atexit.register(server.server_close)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    return server, url


def open_browser_fallback(url: str) -> None:
    print("pywebview 未安装，已回退到浏览器模式。")
    print(f"Open: {url}")
    webbrowser.open(url)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        return


def main() -> None:
    _server, url = start_local_server()

    try:
        import webview
    except ImportError:
        open_browser_fallback(url)
        return

    webview.create_window(
        "TeachAgent",
        url=url,
        width=1520,
        height=980,
        min_size=(1180, 760),
        background_color="#f4efe6",
        text_select=True,
    )
    webview.start()


if __name__ == "__main__":
    main()
