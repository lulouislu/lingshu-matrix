"""Exercise the actual portable executable without probing external targets.

Requires an unused loopback port 8765. Uses an isolated temporary database,
no Python/Node on PATH, and never stops an already-running application.
"""
import argparse
import http.cookiejar
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

URL = "http://127.0.0.1:8765"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    args = parser.parse_args()
    executable = args.executable.resolve()
    assert executable.is_file(), executable
    with socket.socket() as check:
        if check.connect_ex(("127.0.0.1", 8765)) == 0:
            raise SystemExit("Port 8765 is already in use. Existing application was left untouched.")
    environment = dict(os.environ)
    environment["PATH"] = os.pathsep.join([os.path.join(os.environ["SystemRoot"], "System32"), os.environ["SystemRoot"]])
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment.pop("MACNET_DATA_DIR", None)
    environment["PYTHONIOENCODING"] = "utf-8"
    runtime = subprocess.run([str(executable), "--check-runtime"], env=environment,
                             stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
    assert runtime.returncode == 0, runtime.stderr.decode(errors="replace")
    assert json.loads(runtime.stdout)["certificate_verification"] is True
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(URL + path, data=data, headers={"Content-Type": "application/json", "X-MacNet": "1"})
        with opener.open(req, timeout=30) as response:
            return json.load(response)

    with tempfile.TemporaryDirectory(prefix="macnet-portable-") as folder:
        root = Path(folder)
        data_dir = root / "中文测试数据"
        command = [str(executable), "--no-browser", "--data-dir", str(data_dir)]
        with (root / "launch.log").open("w+b") as log:
            process = None
            try:
                for restart in (False, True):
                    process = subprocess.Popen(command, cwd=root, env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
                    deadline = time.monotonic() + 60
                    while True:
                        if process.poll() is not None:
                            raise RuntimeError(f"Executable exited before ready: {process.returncode}")
                        try:
                            health = request("/api/health")
                            assert health["product"] == "macnet-lab" and health["instance"]
                            marker = json.loads((data_dir / "runtime.json").read_text())
                            assert health["instance"] == marker["instance"]
                            break
                        except (OSError, urllib.error.URLError):
                            if time.monotonic() > deadline:
                                raise RuntimeError("Executable never became ready")
                            time.sleep(0.2)
                    request("/api/session")
                    with opener.open(URL, timeout=10) as response:
                        html = response.read().decode()
                    assert 'type="module"' in html and '/assets/' in html
                    state = request("/api/state")
                    observed_deadline = time.monotonic() + 30
                    while not state["context"].get("supported_platform"):
                        assert time.monotonic() < observed_deadline, "Native observation did not become available"
                        time.sleep(0.2)
                        state = request("/api/state")
                    site = state["active_site"]
                    assert not state["monitoring"]
                    if not restart:
                        site["name"] = "Portable persistence · 合成验收"
                        site = request("/api/sites", site)
                        result = request("/api/probes/host-resources/run", {})
                        assert result["status"] == "healthy", result
                    else:
                        assert site["name"] == "Portable persistence · 合成验收"
                    report = request(f"/api/sites/{site['id']}/diagnostics", {"issue": "便携包本机资源与导出验收；未检测外部地址"})
                    assert report["report"]["schema"] == "macnet.diagnostic-report"
                    assert report["report"]["schema_version"] == 1 and report["markdown"]
                    assert "这台电脑" in report["report"]["ai_handoff_instructions"]
                    assert report["report"]["current_observation"]["context"]["platform"] == "win32"
                    duplicate = subprocess.run(command, cwd=root, env=environment, stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
                    assert duplicate.returncode == 0, duplicate.stderr.decode(errors="replace")
                    other = subprocess.run([str(executable), "--no-browser", "--data-dir", str(root / "other")],
                                           cwd=root, env=environment, stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
                    assert other.returncode == 1
                    assert not (root / "other").exists()
                    assert process.poll() is None
                    request("/api/shutdown", {})
                    assert process.wait(timeout=20) == 0
                print("PASS: verified TLS context, Windows credential backend (no credential access), standalone startup, bundled UI, local resource probe, Markdown/JSON, duplicate reuse, different-data refusal, graceful exit and persisted restart.")
            except BaseException:
                log.seek(0)
                print(log.read().decode(errors="replace"), file=sys.stderr)
                raise
            finally:
                if process is not None and process.poll() is None:
                    # This is only the child started above, never a pre-existing service.
                    try:
                        marker = json.loads((data_dir / "runtime.json").read_text())
                        if request("/api/health").get("instance") == marker["instance"]:
                            request("/api/session")
                            request("/api/shutdown", {})
                            process.wait(timeout=20)
                    except Exception:
                        process.terminate()
                        process.wait(timeout=10)


if __name__ == "__main__":
    main()
