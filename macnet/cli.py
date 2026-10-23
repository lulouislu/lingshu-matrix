import argparse
import os
import sys
import threading
import webbrowser


def main():
    parser = argparse.ArgumentParser(description="MacNet Lab · macOS 拓扑感知运维工作台")
    parser.add_argument("--data-dir", help="数据库与本地诊断数据目录")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--preview", action="store_true", help="在非 macOS 环境预览通用界面，不模拟 macOS 采集")
    args = parser.parse_args()
    if sys.platform != "darwin" and not args.preview:
        parser.error("本产品面向 macOS。开发预览请显式指定 --preview")
    if args.data_dir:
        os.environ["MACNET_DATA_DIR"] = args.data_dir
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:8765")).start()
    import uvicorn
    from .app import create_app
    uvicorn.run(create_app(), host="127.0.0.1", port=8765, workers=1, access_log=False)


if __name__ == "__main__":
    main()
