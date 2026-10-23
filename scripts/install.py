"""Build and install MacNet Lab in a project-local venv on Windows or macOS."""
from pathlib import Path
import shutil
import subprocess
import sys
import venv


def main():
    if sys.platform not in ("win32", "darwin"):
        raise SystemExit("This installer targets Windows and macOS.")
    if sys.version_info < (3, 11):
        raise SystemExit("Python 3.11+ is required. Do not replace the OS Python.")
    root = Path(__file__).resolve().parent.parent
    node, npm = shutil.which("node"), shutil.which("npm.cmd" if sys.platform == "win32" else "npm")
    if not node or not npm:
        raise SystemExit("Install compatible Node.js 22.12+ with npm first; use Node 22.x on macOS 12.")
    subprocess.run([node, "-e", 'const [a,b]=process.versions.node.split(".").map(Number);if(a<22||(a===22&&b<12))throw Error("Node 22.12+ required")'], check=True)
    def run(args):
        subprocess.run(args, cwd=root, check=True)
    run([npm, "--prefix", "frontend", "ci"])
    run([npm, "--prefix", "frontend", "run", "build"])
    python = root / (".venv/Scripts/python.exe" if sys.platform == "win32" else ".venv/bin/python")
    if not python.exists():
        venv.EnvBuilder(with_pip=True).create(root / ".venv")
    run([str(python), "-c", "import sys;assert sys.version_info>=(3,11),'Project venv needs Python 3.11+'"])
    run([str(python), "-m", "pip", "install", "--upgrade", "pip"])
    run([str(python), "-m", "pip", "install", "."])
    print("Installed. No probes, login tasks, firewall or network settings were changed.")
    print(r"Start: .\.venv\Scripts\macnet-lab.exe" if sys.platform == "win32" else "Start: .venv/bin/macnet-lab")


if __name__ == "__main__":
    main()
