from __future__ import annotations

import asyncio
import contextlib
import json
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import asyncssh
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .reports import build_report, markdown_report
from .models import DiagnosticRequest, Credential, Site, sanitized_export
from .store import Store, Conflict, uid
from .security import Vault
from .ssh import SSH
from .probes import Probes
from .engine import Engine
from .examples import template


def default_directory():
    return Path(os.environ.get("MACNET_DATA_DIR", str(Path.home() / "Library" / "Application Support" / "MacNetLab")))


class Monitoring(BaseModel):
    enabled: bool


class KnownHosts(BaseModel):
    text: str = Field(min_length=1, max_length=64000)


class Retention(BaseModel):
    days: int = Field(ge=1, le=30)


def create_app(directory=None):
    store = Store(Path(directory) if directory else default_directory())
    vault = Vault()
    ssh = SSH(store.directory, vault)
    engine = Engine(store, Probes(ssh, vault))
    token = secrets.token_urlsafe(32)
    if not store.sites():
        site = store.save(template())
        store.set_setting("active_site", site.id)
    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(engine.loop())
        yield
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    app = FastAPI(title="MacNet Lab", version=__version__, lifespan=lifespan)
    app.state.store, app.state.engine, app.state.vault = store, engine, vault

    def host_allowed(value):
        try:
            return urlsplit("//" + value).hostname in ("127.0.0.1", "localhost", "::1")
        except ValueError:
            return False

    def origin_allowed(value):
        if not value:
            return True  # CLI clients still need session cookie + custom header.
        u = urlsplit(value)
        return u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost") and u.port in (8765, 5173, None)

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        if not host_allowed(request.headers.get("host", "")) or not origin_allowed(request.headers.get("origin")):
            return JSONResponse({"detail": "仅接受本机工作台来源"}, status_code=403)
        if int(request.headers.get("content-length", "0") or 0) > 2_000_000:
            return JSONResponse({"detail": "请求超过 2 MB 限制"}, status_code=413)
        if request.url.path.startswith("/api/") and request.url.path not in ("/api/session", "/api/health"):
            if not secrets.compare_digest(request.cookies.get("macnet_session", ""), token):
                return JSONResponse({"detail": "会话已过期，请刷新页面"}, status_code=401)
            if request.method not in ("GET", "HEAD") and request.headers.get("x-macnet") != "1":
                return JSONResponse({"detail": "请求缺少工作台确认头"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/") else "no-cache"
        return response

    @app.exception_handler(ValueError)
    async def bad_request(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        return JSONResponse({"detail": [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]}, status_code=422)

    def get_site(id):
        site = store.site(id)
        if not site:
            raise HTTPException(404, "站点不存在")
        return site

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__}

    @app.get("/api/session")
    def session():
        response = JSONResponse({"version": __version__})
        response.set_cookie("macnet_session", token, httponly=True, samesite="strict", max_age=86400)
        return response

    @app.get("/api/state")
    def state():
        site = engine.active()
        context = dict(engine.context)
        mapped = []
        if site:
            for iface in context.get("interfaces", []):
                bssid = iface.get("wifi", {}).get("bssid")
                matches = [d.id for d in site.devices if d.kind == "ap" and bssid and any(bssid.lower() in [x.lower() for x in i.bssids] for i in d.interfaces)]
                if bssid:
                    mapped.append({"interface": iface["id"], "bssid": bssid, "device_id": matches[0] if len(matches) == 1 else None, "ambiguous": len(matches) > 1})
        return {"sites": [{"id": s.id, "name": s.name} for s in store.sites()], "active_site": site.model_dump() if site else None, "monitoring": store.setting("monitoring", False), "context": context, "ap_associations": mapped, "latest": list(engine.latest.values()), "error": engine.last_error, "retention_days": store.setting("retention_days", 7)}

    @app.post("/api/sites")
    async def save(site: Site):
        async with engine.lock:
            old = store.site(site.id)
            saved = store.save(site)
            engine.interrupt("配置已更新")
            if old:
                store.event(site.id, "config_changed", {"message": "拓扑或检测配置更新，旧事件记为中断"})
            engine.publish()
            return saved

    @app.post("/api/templates/{kind}")
    async def new_template(kind: str):
        if kind not in ("ac", "home", "empty"):
            raise ValueError("模板不存在")
        site = Site(id=uid(), name="新站点") if kind == "empty" else template(kind)
        return store.save(site)

    @app.post("/api/import")
    async def import_site(site: Site):
        data = sanitized_export(site)
        data["id"] = uid()
        data["name"] += " · 导入"
        return store.save(Site.model_validate(data))

    @app.get("/api/sites/{id}/export")
    def export(id: str):
        return sanitized_export(get_site(id))

    @app.delete("/api/sites/{id}")
    async def remove(id: str):
        async with engine.lock:
            get_site(id)
            if store.setting("active_site") == id:
                store.set_setting("monitoring", False)
                store.set_setting("active_site", "")
                engine.interrupt("站点删除")
            store.delete_site(id)
        return {"ok": True}

    @app.post("/api/active/{id}")
    async def active(id: str):
        async with engine.lock:
            get_site(id)
            engine.interrupt("站点切换")
            store.set_setting("monitoring", False)
            store.set_setting("active_site", id)
            await engine.refresh_context()
        return {"ok": True}

    @app.post("/api/monitoring")
    async def monitoring(body: Monitoring):
        async with engine.lock:
            if not engine.active():
                raise ValueError("请先选择站点")
            store.set_setting("monitoring", body.enabled)
            if not body.enabled:
                engine.interrupt("用户暂停采集")
            store.event(engine.active().id, "monitoring", {"enabled": body.enabled})
        return {"ok": True}

    @app.post("/api/probes/{id}/run")
    async def run_probe(id: str):
        return await engine.once(id)

    @app.get("/api/sites/{id}/history")
    def history(id: str, probe: str | None = None):
        get_site(id)
        return store.samples(id, probe, 300)

    @app.get("/api/sites/{id}/incidents")
    def incidents(id: str):
        get_site(id)
        return {"incidents": store.incidents(id), "events": store.events(id)}

    def incident_in_site(site_id, incident):
        get_site(site_id)
        if not any(i["id"] == incident for i in store.incidents(site_id)):
            raise HTTPException(404, "事件不存在")

    @app.get("/api/sites/{id}/incidents/{incident}")
    def evidence(id: str, incident: str):
        incident_in_site(id, incident)
        return store.evidence(incident)

    @app.post("/api/sites/{id}/incidents/{incident}/snapshot")
    async def snapshot(id: str, incident: str):
        incident_in_site(id, incident)
        await engine.snapshot(get_site(id), incident)
        return store.evidence(incident)

    @app.post("/api/credentials")
    def credentials(body: Credential):
        vault.put(body)
        return {"ok": True, "id": body.id}

    @app.post("/api/known-hosts")
    def known_hosts(body: KnownHosts):
        records = [line.split() for line in body.text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
        if not records:
            raise ValueError("至少提供一条已核实的主机公钥")
        for record in records:
            offset = 2 if record[0].startswith("@") else 1
            try:
                asyncssh.import_public_key(" ".join(record[offset:]))
            except Exception as e:
                raise ValueError("known_hosts 公钥格式无效") from e
        asyncssh.import_known_hosts(body.text)
        ssh.known_hosts.write_text(body.text, encoding="utf-8")
        ssh.known_hosts.chmod(0o600)
        return {"ok": True}

    @app.post("/api/retention")
    async def retention(body: Retention):
        async with engine.lock:
            store.set_setting("retention_days", body.days)
            store.cleanup(body.days)
        return {"ok": True}

    @app.post("/api/sites/{id}/diagnostics")
    async def diagnostics(id: str, body: DiagnosticRequest):
        async with engine.lock:
            get_site(id)
            report = build_report(store, engine, id, body)
        return {"report": report, "markdown": markdown_report(report)}

    # Explicit retirement: stale clients must never send evidence to a model.
    @app.api_route("/api/ai/{operation}", methods=["GET", "POST"])
    def retired_ai(operation: str):
        raise HTTPException(410, "软件内 AI 接入已移除。请在「诊断导出」生成问题日记或 JSON，自行交给 AI。")

    @app.websocket("/api/live")
    async def live(websocket: WebSocket):
        if not origin_allowed(websocket.headers.get("origin")) or not host_allowed(websocket.headers.get("host", "")) or not secrets.compare_digest(websocket.cookies.get("macnet_session", ""), token):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        queue = asyncio.Queue(maxsize=2)
        engine.observers.add(queue)
        try:
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), 15)
                except TimeoutError:
                    message = {"kind": "heartbeat"}
                await websocket.send_json(message)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            engine.observers.discard(queue)

    static = Path(__file__).parent / "static"
    if static.exists():
        app.mount("/", StaticFiles(directory=static, html=True), name="ui")
    else:
        @app.get("/")
        def unbuilt():
            return JSONResponse({"detail": "前端尚未构建。在 frontend 目录运行 npm ci && npm run build"}, status_code=503)
    return app
