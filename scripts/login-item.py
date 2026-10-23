"""Explicit opt-in launchd user agent. Never installs a system/root daemon."""
import argparse
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import urllib.request

LABEL = "com.macnetlab.workbench"


def main():
    parser = argparse.ArgumentParser(description="Opt-in LingShu Matrix login item")
    parser.add_argument("action", choices=["install", "remove", "status"])
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("launchd integration requires macOS")
    root = Path(__file__).resolve().parent.parent
    binary = root / ".venv/bin/macnet-lab"
    target = Path.home() / "Library/LaunchAgents" / (LABEL + ".plist")
    domain = f"gui/{os.getuid()}"
    if args.action == "status":
        return subprocess.run(["/bin/launchctl", "print", domain + "/" + LABEL]).returncode
    if args.action == "remove":
        if target.exists():
            subprocess.run(["/bin/launchctl", "bootout", domain, str(target)], check=False)
            target.unlink()
        print("Login item removed. Runtime data and Keychain entries are retained.")
        return 0
    if not binary.exists():
        parser.error("Run bash scripts/install-macos.sh first")
    if target.exists():
        parser.error("Login item already exists. Remove it before reinstalling")
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/api/health", timeout=2):
            parser.error("Workbench already running. Stop the manual instance first")
    except OSError:
        pass
    target.parent.mkdir(parents=True, exist_ok=True)
    value = {
        "Label": LABEL, "ProgramArguments": [str(binary), "--no-browser"],
        "WorkingDirectory": str(root), "RunAtLoad": True, "KeepAlive": True,
        "ThrottleInterval": 15,
        "EnvironmentVariables": {"PATH": str(Path.home() / ".local/bin") + ":/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"},
        "StandardOutPath": "/dev/null", "StandardErrorPath": "/dev/null",
    }
    with target.open("xb") as stream:
        plistlib.dump(value, stream)
    target.chmod(0o600)
    result = subprocess.run(["/bin/launchctl", "bootstrap", domain, str(target)])
    if result.returncode:
        target.unlink()
        return result.returncode
    print("Login item installed for this user. Open http://127.0.0.1:8765")
    print("It runs only while you are logged in; sleep still interrupts collection.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
