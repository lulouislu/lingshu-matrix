import asyncio
import json
import sys

import pytest

from macnet import ai


@pytest.mark.asyncio
async def test_codex_protocol_denies_tools_and_restricts_read_roots(tmp_path, monkeypatch):
    """A local protocol fixture: no login, model request, or external connection."""
    fixture = tmp_path / "fake_server.py"
    record = tmp_path / "requests.json"
    fixture.write_text('''import sys,json
requests=[]
def read():
    v=json.loads(sys.stdin.readline());requests.append(v);return v
def emit(v):
    print(json.dumps(v),flush=True)
read();emit({"id":1,"result":{}})
read();read();emit({"id":2,"result":{"thread":{"id":"test-thread"}}})
read();emit({"id":4,"result":{"data":[],"nextCursor":None}})
read();emit({"id":3,"result":{"turn":{"id":"test-turn"}}})
emit({"id":999,"method":"item/commandExecution/requestApproval","params":{}})
read()
with open(sys.argv[1],"w") as f:json.dump(requests,f)
emit({"method":"item/agentMessage/delta","params":{"delta":"fixture response"}})
emit({"method":"turn/completed","params":{"turn":{"status":"completed"}}})
''', encoding="utf-8")
    original_spawn = asyncio.create_subprocess_exec
    async def spawn(*args, **kwargs):
        assert "features.shell_tool=false" in args
        assert "mcp_servers={}" in args
        assert kwargs["env"]["CODEX_HOME"] == str((tmp_path / "codex-home").resolve())
        return await original_spawn(sys.executable, str(fixture), str(record), **kwargs)
    monkeypatch.setattr(ai.shutil, "which", lambda _: sys.executable)
    monkeypatch.setattr(ai.asyncio, "create_subprocess_exec", spawn)
    assert await ai.codex_answer("local fixture", tmp_path) == "fixture response"
    rows = json.loads(record.read_text())
    turn = next(r for r in rows if r.get("method") == "turn/start")
    policy = turn["params"]["sandboxPolicy"]
    assert policy["type"] == "readOnly"
    assert policy["access"]["type"] == "restricted"
    assert len(policy["access"]["readableRoots"]) == 1
    assert rows[-1]["id"] == 999 and "error" in rows[-1]


@pytest.mark.asyncio
async def test_compatible_local_model_does_not_need_a_keychain_or_external_call(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import httpx
    from macnet.models import AIRequest, Site
    from macnet.store import Store
    store = Store(tmp_path)
    site = store.save(Site(id="site", name="Fixture"))
    store.set_setting("ai_config", {"endpoint": "http://127.0.0.1:12345/v1", "model": "fixture"})
    def respond(request):
        assert "authorization" not in request.headers
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(200, json={"choices": [{"message": {"content": "synthetic answer"}}]})
    original = httpx.AsyncClient
    monkeypatch.setattr(ai.httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    value = await ai.answer(store, SimpleNamespace(context={}), site, AIRequest(question="check", provider="compatible", share_evidence=True), None)
    assert value["answer"] == "synthetic answer" and value["provider"] == "compatible"
