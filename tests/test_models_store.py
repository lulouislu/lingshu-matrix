import pytest
from pydantic import ValidationError

from macnet.models import Device, Interface, Link, Probe, Result, Site, sanitized_export
from macnet.security import redact
from macnet.store import Conflict, Store


def site():
    return Site(id="lab", name="Lab", devices=[Device(id="mac", label="Mac", kind="mac", credential_ref="private-ref", interfaces=[Interface(id="en0")])])


def test_link_references_real_interface():
    data = site().model_dump()
    data["devices"].append(Device(id="ap", label="AP").model_dump())
    data["links"] = [Link(id="link", source="ap", target="mac", target_interface="not-present").model_dump()]
    with pytest.raises(ValidationError):
        Site.model_validate(data)


def test_export_cannot_carry_credentials_or_start_probes():
    value = site()
    value.probes = [Probe(id="p", device_id="mac", label="Check", kind="tcp", enabled=True)]
    exported = sanitized_export(value)
    assert exported["devices"][0]["credential_ref"] == ""
    assert not exported["probes"][0]["enabled"]


def test_duplicate_ids_rejected():
    with pytest.raises(ValidationError):
        Site(id="lab", name="Lab", devices=[Device(id="mac", label="A"), Device(id="mac", label="B")])


def test_embedded_password_rejected():
    with pytest.raises(ValidationError):
        Probe(id="p", device_id="mac", label="Check", kind="http", target="https://user:password@example.com")


def test_optimistic_lock_and_incident(tmp_path):
    db = Store(tmp_path)
    value = db.save(site())
    assert value.revision == 1
    with pytest.raises(Conflict):
        db.save(site())
    incident = db.open_incident("lab", "p", {"message": "failed"})
    db.sample("lab", "p", Result(status="failed", message="timeout"))
    db.evidence(incident, {"message": "snapshot"})
    db.finish(incident)
    assert db.incidents("lab")[0]["status"] == "resolved"
    assert db.evidence(incident)[0]["body"]["message"] == "snapshot"
    assert db.samples("lab")[0]["status"] == "failed"


def test_redaction():
    result = redact({"api_token": "secret", "output": "password=hidden\nurl https://subscription.example/token"})
    assert "secret" not in str(result)
    assert "hidden" not in str(result)
    assert "subscription.example" not in str(result)


def test_connections_close_and_capacity_limit_applies_to_every_connection(tmp_path):
    import sqlite3
    db = Store(tmp_path)
    with db.connect() as connection:
        assert connection.execute("PRAGMA max_page_count").fetchone()[0] == 131072
    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")
    with db.connect() as other:
        assert other.execute("PRAGMA max_page_count").fetchone()[0] == 131072
