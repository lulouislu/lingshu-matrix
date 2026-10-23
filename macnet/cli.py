import argparse
import os
import sys
import threading
import webbrowser


def main():
    parser = argparse.ArgumentParser(description="MacNet Lab · Windows / macOS 跨平台运维工作台")
    parser.add_argument("--data-dir", help="数据库与本地诊断数据目录")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--preview", action="store_true", help="在其他系统预览通用界面，不模拟平台采集")
    args = parser.parse_args()
    if sys.platform not in ("darwin", "win32") and not args.preview:
        parser.error("当前原生适配 Windows 和 macOS；其他系统开发预览请指定 --preview")
    if args.data_dir:
        os.environ["MACNET_DATA_DIR"] = args.data_dir
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:8765")).start()
    import uvicorn
    from .app import create_app
    uvicorn.run(create_app(), host="127.0.0.1", port=8765, workers=1, access_log=False)


if __name__ == "__main__":
    main()
