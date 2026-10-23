from __future__ import annotations

import asyncio
import json
import time
import shutil
from .models import Result
from .platform import observation, resource_info
from .security import redact


class Engine:
    def __init__(self, store, probes):
        self.store, self.probes = store, probes
        self.lock = asyncio.Lock()
        self.context = {"interfaces": []}
        self.latest = {}
        self.states = {}
        self.due = {}
        self.observers = set()
        self.last_tick = time.time()
        self.last_context = 0
        self.last_cleanup = 0
        self.last_fingerprint = None
        self.last_error = ""
        for site in store.sites():
            for incident in store.incidents(site.id):
                if incident["status"] == "open":
                    store.finish(incident["id"], "interrupted")
            if store.samples(site.id, limit=1):
                store.event(site.id, "monitor_gap", {"message": "程序重新启动，停机期间无检测证据"})

    def active(self):
        return self.store.site(self.store.setting("active_site", ""))

    def publish(self):
        for queue in list(self.observers):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait({"kind": "refresh", "at": time.time()})

    async def refresh_context(self):
        current = await observation()
        # Signal strength does not define a new observation position.
        identity = json.dumps([{k: i.get(k) for k in ("id", "up", "addresses", "route")} | {"bssid": i.get("wifi", {}).get("bssid")} for i in current["interfaces"]], sort_keys=True)
        if self.last_fingerprint is not None and identity != self.last_fingerprint and self.active():
            self.store.event(self.active().id, "access_changed", {"message": "接口、地址、网关或 AP 关联变化", "context": current})
            self.interrupt("观测位置改变，旧路径事件中断而非已恢复")
        self.context, self.last_fingerprint = current, identity
        self.last_context = time.time()

    def interrupt(self, reason):
        for state in self.states.values():
            if state.get("incident"):
                self.store.finish(state["incident"], "interrupted")
        self.states.clear()
        self.due.clear()
        self.latest.clear()
        self.last_error = ""

    async def check(self, site, probe):
        device = next(d for d in site.devices if d.id == probe.device_id)
        result = await self.probes.run(probe, device, self.context)
        result = Result.model_validate(redact(result.model_dump()))
        key = site.id + ":" + probe.id
        self.latest[key] = {"probe": probe.id, "at": time.time(), **result.model_dump()}
        self.store.sample(site.id, probe.id, result)
        state = self.states.setdefault(key, {"failures": 0, "successes": 0, "incident": None})
        if result.status == "failed":
            state["failures"] += 1
            state["successes"] = 0
            if state["failures"] >= probe.failures and not state["incident"]:
                state["incident"] = self.store.open_incident(site.id, probe.id, {"probe_label": probe.label, "device": device.label, "result": result.model_dump()})
                await self.snapshot(site, state["incident"], probe)
        elif result.status == "healthy":
            state["failures"] = 0
            state["successes"] += 1
            if state["incident"] and state["successes"] >= 2:
                self.store.evidence(state["incident"], redact({"phase": "recovery", "result": result.model_dump(), "context": self.context}))
                self.store.finish(state["incident"])
                state["incident"] = None
        else:
            state["failures"] = state["successes"] = 0
        self.publish()
        return result

    async def snapshot(self, site, incident, probe=None):
        evidence = {"topology": site.model_dump(), "phase": "failure" if probe else "manual", "context": self.context, "resources": resource_info(), "recent_samples": self.store.samples(site.id, limit=80)}
        if probe and probe.collect_snapshot:
            device = next(d for d in site.devices if d.id == probe.device_id)
            if device.credential_ref:
                try:
                    evidence["ssh"] = {"path": "系统管理路径，不代表故障检测接口", **await self.probes.ssh.collect(device, "openwrt" if device.kind == "gateway" else "system")}
                except Exception as e:
                    evidence["ssh"] = {"status": "unavailable", "reason": str(e)}
        self.store.evidence(incident, redact(evidence))

    async def once(self, probe_id):
        async with self.lock:
            site = self.active()
            if not site:
                raise ValueError("先选择站点")
            probe = next((p for p in site.probes if p.id == probe_id), None)
            if not probe:
                raise ValueError("检测不存在")
            await self.refresh_context()
            return await self.check(site, probe)

    async def loop(self):
        while True:
            try:
                async with self.lock:
                    now = time.time()
                    if now - self.last_tick > 60:
                        site = self.active()
                        if site:
                            self.store.event(site.id, "monitor_gap", {"message": "宿主机休眠或调度中断超过 60 秒；期间无检测证据"})
                        self.interrupt("调度中断")
                    self.last_tick = now
                    if now - self.last_context >= 20:
                        await self.refresh_context()
                        self.publish()
                    site = self.active()
                    if site and self.store.setting("monitoring", False):
                        if shutil.disk_usage(self.store.directory).free < 256 * 1024 * 1024:
                            self.store.set_setting("monitoring", False)
                            self.last_error = "数据盘剩余空间不足 256 MB，已暂停自动采集"
                            self.publish()
                            continue
                        ready = [p for p in site.probes if p.enabled and self.due.get(site.id + ":" + p.id, 0) <= now]
                        semaphore = asyncio.Semaphore(8)
                        async def run(p):
                            async with semaphore:
                                await self.check(site, p)
                                self.due[site.id + ":" + p.id] = time.time() + p.interval
                        await asyncio.gather(*(run(p) for p in ready))
                    if now - self.last_cleanup > 3600:
                        self.store.cleanup(self.store.setting("retention_days", 7))
                        self.last_cleanup = now
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.last_error = str(e)
                self.publish()
            await asyncio.sleep(1)
