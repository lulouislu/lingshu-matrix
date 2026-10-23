"""Build a Windows x64 onedir ZIP; no user data or source venv is included."""
import argparse
import importlib.metadata
from pathlib import Path
import platform
import re
import shutil
import ssl
import subprocess
import sys
import tomllib


def copy_licenses(root, bundle):
    """Preserve available license/notice files from the runtime dependency closure."""
    from packaging.requirements import Requirement
    pending = [Requirement(item) for item in tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]]
    pending.append(Requirement("pyinstaller"))  # The executable embeds its bootloader.
    visited, copied = set(), set()
    notices = ["MacNet Lab runtime dependencies and build bootloader. See licenses/ for supplied licenses and notices.\n"]
    while pending:
        requirement = pending.pop()
        if requirement.marker and not requirement.marker.evaluate():
            continue
        key = (requirement.name.lower(), frozenset(requirement.extras))
        if key in visited:
            continue
        visited.add(key)
        distribution = importlib.metadata.distribution(requirement.name)
        destination = bundle / "licenses" / re.sub(r"[^A-Za-z0-9_.-]", "_", distribution.metadata["Name"])
        if destination.name not in copied:
            copied.add(destination.name)
            destination.mkdir(parents=True, exist_ok=True)
            notices.append(f"{distribution.metadata['Name']} {distribution.version}\n")
            (destination / "METADATA.txt").write_text(distribution.read_text("METADATA") or
                f"Name: {distribution.metadata['Name']}\nVersion: {distribution.version}\n", encoding="utf-8")
            for file in distribution.files or []:
                if re.match(r"(?i)(licen[cs]e|copying|notice)(\b|[._-])", file.name):
                    source = Path(distribution.locate_file(file))
                    if source.is_file():
                        # Preserve package-relative locations to avoid duplicate basenames.
                        relative = Path(*[part for part in file.parts if part not in ("..", ".")])
                        target = destination / relative
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, target)
        for item in distribution.requires or []:
            child = Requirement(item)
            if child.marker is None or any(child.marker.evaluate({"extra": extra}) for extra in requirement.extras or {""}):
                # Markers have already been evaluated with the parent's requested extras.
                child.marker = None
                pending.append(child)
    (bundle / "THIRD_PARTY_NOTICES.txt").write_text("\n".join(notices), encoding="utf-8")
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise RuntimeError("Python's LICENSE.txt was not found; do not distribute without it.")
    shutil.copy2(python_license, bundle / "licenses/Python-LICENSE.txt")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("dist/windows"))
    parser.add_argument("--work", type=Path, default=Path("build/windows"))
    args = parser.parse_args()
    if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64") or sys.maxsize <= 2**32:
        parser.error("Use Windows with 64-bit x64 Python. This build is not an ARM64 package.")
    root = Path(__file__).resolve().parent.parent
    if not (root / "macnet/static/index.html").is_file():
        parser.error("Build the frontend first: npm --prefix frontend ci && npm --prefix frontend run build")
    output, work = args.output.resolve(), args.work.resolve()
    output.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--console",
               "--noupx", "--name", "MacNetLab", "--distpath", str(output), "--workpath", str(work / "analysis"),
               "--specpath", str(work), "--paths", str(root), "--add-data", f"{root / 'macnet/static'}:macnet/static",
               "--copy-metadata", "keyring", "--hidden-import", "keyring.backends.Windows",
               "--hidden-import", "uvicorn.logging", "--hidden-import", "uvicorn.loops.asyncio",
               "--hidden-import", "uvicorn.protocols.http.h11_impl",
               "--hidden-import", "uvicorn.protocols.websockets.websockets_impl",
               "--hidden-import", "uvicorn.lifespan.on"]
    # Some managed Python runtimes add an adjacent public CA policy file to
    # ssl.py. Preserve it when present; never disable certificate verification.
    ssl_policy = Path(ssl.__file__).parent / "codex-rejected-cas.pem"
    if ssl_policy.is_file():
        command.extend(["--add-data", f"{ssl_policy}:."])
    command.append(str(root / "scripts/portable_entry.py"))
    subprocess.run(command, cwd=root, check=True)
    bundle = output / "MacNetLab"
    shutil.copy2(root / "LICENSE", bundle / "LICENSE.txt")
    shutil.copy2(root / "docs/WINDOWS_PORTABLE.md", bundle / "START_HERE.md")
    shutil.copy2(root / "scripts/start-portable.cmd", bundle / "Start-MacNetLab.cmd")
    copy_licenses(root, bundle)
    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    archive = shutil.make_archive(str(output / f"macnet-lab-{version}-windows-x64"), "zip", output, "MacNetLab")
    print(f"\nPortable ZIP: {archive}\nUnzip the whole folder, then double-click MacNetLab.exe.")


if __name__ == "__main__":
    main()
