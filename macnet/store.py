from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from .models import Site, Result


def uid():
    return uuid.uuid4().hex[:16]


class Conflict(Exception):
    pass


class Store:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = directory / "macnet.sqlite3"
        with self.connect() as c:
            c.executescript("""
            PRAGMA auto_vacuum=INCREMENTAL;
            PRAGMA max_page_count=131072;
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS sites(id TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS samples(id INTEGER PRIMARY KEY, site TEXT, probe TEXT, at REAL, body TEXT);
            CREATE INDEX IF NOT EXISTS sample_lookup ON samples(site,probe,at);
            CREATE TABLE IF NOT EXISTS incidents(id TEXT PRIMARY KEY, site TEXT, probe TEXT, started REAL,
              ended REAL, status TEXT, body TEXT);
            CREATE TABLE IF NOT EXISTS evidence(id TEXT PRIMARY KEY, incident TEXT, at REAL, body TEXT);
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, site TEXT, at REAL, kind TEXT, body TEXT);
            CREATE TABLE IF NOT EXISTS actions(id TEXT PRIMARY KEY, site TEXT, device TEXT, at REAL, state TEXT, body TEXT);
            """)
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.path, timeout=15)
        c.row_factory = sqlite3.Row
        try:
            c.execute("PRAGMA max_page_count=131072")
            with c:
                yield c
        finally:
            c.close()

    def setting(self, key, default=None):
        with self.connect() as c:
            row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        with self.connect() as c:
            c.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value)))

    def sites(self):
        with self.connect() as c:
            return [Site.model_validate_json(r[0]) for r in c.execute("SELECT body FROM sites ORDER BY id")]

    def site(self, id):
        with self.connect() as c:
            row = c.execute("SELECT body FROM sites WHERE id=?", (id,)).fetchone()
        return Site.model_validate_json(row[0]) if row else None

    def save(self, site: Site):
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT body FROM sites WHERE id=?", (site.id,)).fetchone()
            revision = json.loads(row[0])["revision"] if row else 0
            if revision != site.revision:
                raise Conflict("站点已在其他窗口更新，请重新载入后编辑")
            saved = site.model_copy(update={"revision": revision + 1})
            c.execute("INSERT OR REPLACE INTO sites VALUES (?,?)", (saved.id, saved.model_dump_json()))
        return saved

    def delete_site(self, id):
        with self.connect() as c:
            c.execute("DELETE FROM evidence WHERE incident IN (SELECT id FROM incidents WHERE site=?)", (id,))
            for table in ("sites", "samples", "incidents", "events", "actions"):
                c.execute(f"DELETE FROM {table} WHERE {'id' if table == 'sites' else 'site'}=?", (id,))

    def sample(self, site, probe, result: Result, at=None):
        with self.connect() as c:
            # Detail has a separate cap: large printer/SSH output belongs in bounded evidence.
            if len(result.model_dump_json()) > 16000:
                result = result.model_copy(update={"detail": {"truncated": True, "preview": json.dumps(result.detail, ensure_ascii=False)[:12000]}})
            c.execute("INSERT INTO samples(site,probe,at,body) VALUES (?,?,?,?)", (site, probe, at or time.time(), result.model_dump_json()))

    def samples(self, site, probe=None, limit=120):
        sql, params = "SELECT * FROM samples WHERE site=?", [site]
        if probe:
            sql += " AND probe=?"
            params.append(probe)
        with self.connect() as c:
            rows = c.execute(sql + " ORDER BY id DESC LIMIT ?", (*params, min(limit, 2000))).fetchall()
        return [{"id": r["id"], "probe": r["probe"], "at": r["at"], **json.loads(r["body"])} for r in rows]

    def open_incident(self, site, probe, body):
        id = uid()
        with self.connect() as c:
            c.execute("INSERT INTO incidents VALUES (?,?,?,?,?,?,?)", (id, site, probe, time.time(), None, "open", json.dumps(body)))
        return id

    def finish(self, id, status="resolved"):
        with self.connect() as c:
            c.execute("UPDATE incidents SET ended=?,status=? WHERE id=?", (time.time(), status, id))

    def incidents(self, site):
        with self.connect() as c:
            rows = c.execute("SELECT * FROM incidents WHERE site=? ORDER BY started DESC LIMIT 300", (site,)).fetchall()
        return [{**dict(r), "body": json.loads(r["body"])} for r in rows]

    def evidence(self, incident, body=None):
        with self.connect() as c:
            if body is not None:
                encoded = json.dumps(body, ensure_ascii=False)
                if len(encoded) > 160000:
                    encoded = json.dumps({"truncated": True, "preview": encoded[:150000]}, ensure_ascii=False)
                c.execute("INSERT INTO evidence VALUES (?,?,?,?)", (uid(), incident, time.time(), encoded))
            return [{**dict(r), "body": json.loads(r["body"])} for r in c.execute("SELECT * FROM evidence WHERE incident=? ORDER BY at", (incident,))]

    def event(self, site, kind, body):
        with self.connect() as c:
            c.execute("INSERT INTO events(site,at,kind,body) VALUES (?,?,?,?)", (site, time.time(), kind, json.dumps(body)))

    def events(self, site):
        with self.connect() as c:
            return [{**dict(r), "body": json.loads(r["body"])} for r in c.execute("SELECT * FROM events WHERE site=? ORDER BY id DESC LIMIT 100", (site,))]

    def cleanup(self, days=7):
        cutoff = time.time() - days * 86400
        with self.connect() as c:
            c.execute("DELETE FROM samples WHERE at<?", (cutoff,))
            c.execute("DELETE FROM events WHERE at<?", (cutoff,))
            c.execute("DELETE FROM evidence WHERE incident IN (SELECT id FROM incidents WHERE ended<?)", (cutoff,))
            c.execute("DELETE FROM incidents WHERE ended<?", (cutoff,))
            c.execute("DELETE FROM actions WHERE at<? AND state NOT IN ('prepared','running','awaiting_recovery')", (cutoff,))
            c.execute("PRAGMA incremental_vacuum")
            # Hard row caps bound active incidents and samples even at high probe counts.
            c.execute("DELETE FROM samples WHERE id NOT IN (SELECT id FROM samples ORDER BY id DESC LIMIT 200000)")
            c.execute("DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 10000)")
            c.execute("DELETE FROM evidence WHERE id IN (SELECT id FROM evidence ORDER BY at DESC LIMIT -1 OFFSET 2000)")

    def action(self, id=None, body=None):
        with self.connect() as c:
            if body:
                c.execute("INSERT OR REPLACE INTO actions VALUES (?,?,?,?,?,?,?)", (body["id"], body["site"], body["device"], body["at"], body["state"], json.dumps(body)))
            row = c.execute("SELECT body FROM actions WHERE id=?", (id or body["id"],)).fetchone()
        return json.loads(row[0]) if row else None
