"""Local launcher shared by source installs and the Windows portable build."""
import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser

from . import __version__, DISPLAY_NAME

ADDRESS = ("127.0.0.1", 8765)
URL = "http://127.0.0.1:8765"


def reserve_listener(address=ADDRESS):
    """Reserve once, then hand the same socket to Uvicorn (no bind/check race)."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if sys.platform == "win32":
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(address)
        listener.listen(128)
        listener.setblocking(False)
        return listener
    except BaseException:
        listener.close()
        raise


def existing_instance(directory, url=URL, timeout=8):
    """Match this data directory to a live per-launch identity, not just a port.

    The marker is neither a credential nor a lock. A stale marker alone never
    opens a browser. Proxy environment variables are ignored for loopback.
    """
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while True:
        try:
            with opener.open(url + "/api/health", timeout=0.4) as response:
                health = json.loads(response.read(4096))
            if health.get("product") != "macnet-lab" or health.get("status") != "ok":
                return False
            try:
                marker = json.loads((Path(directory) / "runtime.json").read_text(encoding="utf-8"))
            except OSError:
                return False
            return (health.get("product") == "macnet-lab" and health.get("status") == "ok"
                    and isinstance(marker.get("instance"), str) and len(marker["instance"]) == 32
                    and health.get("instance") == marker["instance"])
        except (urllib.error.HTTPError, ValueError, TypeError, AttributeError):
            return False
        except (OSError, urllib.error.URLError):
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.15)


def open_browser():
    try:
        if not webbrowser.open(URL):
            print("浏览器未自动打开，请手动访问 / Open manually: " + URL, flush=True)
    except Exception:
        print("请手动打开浏览器 / Open manually: " + URL, flush=True)


def run(directory, no_browser=False):
    import uvicorn
    from .app import create_app

    directory = Path(directory).expanduser().resolve()
    try:
        listener = reserve_listener()
    except OSError as exc:
        if existing_instance(directory):
            print(DISPLAY_NAME + " 已在运行，打开现有工作台 / Already running: " + URL, flush=True)
            if not no_browser:
                open_browser()
            return 0
        raise RuntimeError(
            "127.0.0.1:8765 已被占用，或另一工作台使用了不同的数据目录。"
            "请先在原窗口按 Ctrl+C 停止原实例；本次未启动，也未打开占用端口的页面。\n"
            "Port 8765 is occupied or the data directory differs. Stop the original instance first."
        ) from exc

    with listener:
        directory.mkdir(parents=True, exist_ok=True)
        identity = secrets.token_hex(16)
        temporary = directory / "runtime.json.tmp"
        temporary.write_text(json.dumps({"instance": identity}), encoding="utf-8")
        temporary.replace(directory / "runtime.json")
        def shutdown():
            server.should_exit = True

        # macOS may be owned by the existing KeepAlive LaunchAgent: leave its
        # stop/remove contract with launchctl instead of reporting a false exit.
        app = create_app(directory, instance_id=identity,
                         shutdown=shutdown if sys.platform == "win32" else None)

        class LocalServer(uvicorn.Server):
            async def startup(self, sockets=None):
                await super().startup(sockets)
                if self.started:
                    print(f"\n{DISPLAY_NAME} {__version__} · {URL}\n数据 / Data: {directory}\n"
                          "保持此窗口运行；退出请按 Ctrl+C。关闭网页不会停止采集。\n"
                          "Keep this window open. Ctrl+C stops the app; closing the browser does not.\n", flush=True)
                    if not no_browser:
                        threading.Thread(target=open_browser, daemon=True).start()

        server = LocalServer(uvicorn.Config(app, host=ADDRESS[0], port=ADDRESS[1], workers=1,
                                           loop="asyncio", http="h11", ws="websockets",
                                           access_log=False, timeout_graceful_shutdown=10))
        server.run(sockets=[listener])
        return 0 if server.started else 1


def main():
    parser = argparse.ArgumentParser(description=DISPLAY_NAME + " · Windows / macOS 跨平台运维工作台")
    parser.add_argument("--version", action="version", version=f"{DISPLAY_NAME} {__version__}")
    parser.add_argument("--data-dir", help="数据库与本地诊断数据目录")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--preview", action="store_true", help="在其他系统预览通用界面，不模拟平台采集")
    args = parser.parse_args()
    if sys.platform not in ("darwin", "win32") and not args.preview:
        parser.error("当前原生适配 Windows 和 macOS；其他系统开发预览请指定 --preview")
    if args.data_dir:
        os.environ["MACNET_DATA_DIR"] = args.data_dir
    from .app import default_directory
    try:
        return run(default_directory(), args.no_browser)
    except KeyboardInterrupt:
        return 0
    except (OSError, RuntimeError) as exc:
        print(f"\n启动失败 / Unable to start:\n{exc}", file=sys.stderr, flush=True)
        if sys.platform == "win32" and getattr(sys, "frozen", False) and sys.stdin.isatty():
            try:
                input("按 Enter 关闭此窗口 / Press Enter to close…")
            except EOFError:
                pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
