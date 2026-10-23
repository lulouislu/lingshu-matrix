"""Branding changes must not strand existing data, imports or launch commands."""
import json
from pathlib import Path
from types import SimpleNamespace
import tomllib

from fastapi.testclient import TestClient

from macnet import DISPLAY_NAME, __version__
from macnet.app import create_app
from macnet.models import DiagnosticRequest, Site
from macnet.reports import build_report, markdown_report
from macnet.security import Vault
from macnet.store import Store


def test_release_metadata_and_legacy_entry_points():
    root = Path(__file__).resolve().parents[1]
    metadata = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    frontend = json.loads((root / "frontend/package.json").read_text(encoding="utf-8"))
    lock = json.loads((root / "frontend/package-lock.json").read_text(encoding="utf-8"))
    assert metadata["version"] == frontend["version"] == lock["version"] == lock["packages"][""]["version"] == __version__
    assert metadata["name"] == "macnet-lab"
    assert metadata["scripts"]["lingshu-matrix"] == metadata["scripts"]["macnet-lab"] == "macnet.cli:main"
    assert metadata["license"] == "MIT"
    assert "Copyright (c) 2026 Zhenyu Lu (lulouislu)" in (root / "LICENSE").read_text(encoding="utf-8")
    assert Vault.SERVICE == "MacNetLab"


def test_display_brand_does_not_change_instance_protocol(tmp_path):
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1:8765") as client:
        health = client.get("/api/health").json()
        assert health["name"] == DISPLAY_NAME == "灵枢 · LingShu Matrix"
        assert health["product"] == "macnet-lab"  # Existing instances still recognize each other.
        assert health["version"] == __version__


def test_new_report_name_preserves_old_schema_and_topology(tmp_path):
    store = Store(tmp_path)
    site = store.save(Site(id="existing-site", name="Existing topology"))
    engine = SimpleNamespace(context={}, last_context=0)
    report = build_report(store, engine, site.id, DiagnosticRequest(issue="Existing data after rename"))
    assert report["schema"] == "macnet.diagnostic-report" and report["schema_version"] == 1
    assert report["topology"]["id"] == "existing-site"
    assert report["application"] == {"name": DISPLAY_NAME, "version": __version__}
    assert markdown_report(report).startswith("# 灵枢 · LingShu Matrix 网络问题日记")
