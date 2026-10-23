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
    parser.add_argument("--codex-login", action="store_true", help="通过官方 CLI 登录本工具独立的 Codex 配置，不读取桌面端凭据")
    args = parser.parse_args()
    if sys.platform != "darwin" and not args.preview:
        parser.error("本产品面向 macOS。开发预览请显式指定 --preview")
    if args.data_dir:
        os.environ["MACNET_DATA_DIR"] = args.data_dir
    if args.codex_login:
        import shutil
        import subprocess
        from .ai import codex_environment
        from .app import default_directory
        binary = shutil.which("codex")
        if not binary:
            parser.error("请先安装官方 Codex CLI")
        raise SystemExit(subprocess.run([binary, "login"], env=codex_environment(default_directory())).returncode)
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:8765")).start()
    import uvicorn
    from .app import create_app
    uvicorn.run(create_app(), host="127.0.0.1", port=8765, workers=1, access_log=False)


if __name__ == "__main__":
    main()
