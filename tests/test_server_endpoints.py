"""M6 — HTTP server endpoints: /status and /history (the noise-filtered transcript).

Stdlib unittest + FastAPI TestClient. /chat is covered in test_chat_context.py.
"""

import threading
import unittest

from assistant_core.server import AssistantServer, _fastapi_available
from assistant_core.providers.base_provider import Message


class _Router:
    available_providers = ["groq"]

    def status(self):
        return {"groq": True, "google": False, "webui": True}


class _FakeReg:
    """Minimal tool registry: echoes the tool name + input (no LLM)."""
    def __init__(self):
        self.calls = []

    def run(self, tool_name, tool_input):
        from types import SimpleNamespace
        self.calls.append((tool_name, tool_input))
        return SimpleNamespace(success=True, output=f"[{tool_name}] {tool_input}")


@unittest.skipUnless(_fastapi_available, "fastapi/httpx not installed")
class ServerEndpointsTests(unittest.TestCase):
    def _client(self, history=None, registry=None):
        from fastapi.testclient import TestClient
        server = AssistantServer(
            router=_Router(), memory=None, registry=registry,
            history=[] if history is None else history,
            history_lock=threading.Lock(), config={"host": "127.0.0.1"}, system_prompt="SYS",
        )
        return TestClient(server._app)

    def test_vault_command_runs_tool_directly_not_llm(self):   # T5.01 fix
        reg = _FakeReg()
        d = self._client(registry=reg).post("/chat", json={"message": "vault:search rocket"}).json()
        self.assertEqual(d["provider_used"], "system")          # not routed to an LLM
        self.assertIn("search_vault", d["reply"])                # the tool ran
        self.assertEqual(reg.calls[0][0], "search_vault")

    def test_vault_research_triggers_handoff_roundtrip(self):   # M20 round-trip
        reg = _FakeReg()
        d = self._client(registry=reg).post(
            "/chat", json={"message": "vault:research how do rocket stoves work"}).json()
        self.assertEqual(d["status"], "handoff_required")        # paste-back UI, not a plain reply
        self.assertIn("generate_research_prompt", d["prompt_to_copy"])
        self.assertEqual(reg.calls[0][0], "generate_research_prompt")

    def test_natural_language_research_becomes_handoff(self):   # plain "search the web…"
        import threading as _t
        from fastapi.testclient import TestClient
        class _R:
            available_providers = ["groq"]
            registry = type("Reg", (), {"spec": lambda self, n: None})()   # trim → no-op
            def status(self): return {"groq": True}
            def generate(self, messages, system_prompt="", **kw):
                return "Sure.\nvault:research How to make an oral rehydration solution", "groq"
        reg = _FakeReg()
        server = AssistantServer(
            router=_R(), memory=None, registry=reg, history=[], history_lock=_t.Lock(),
            config={"host": "127.0.0.1"}, system_prompt="SYS")
        d = TestClient(server._app).post(
            "/chat", json={"message": "search the web for oral rehydration"}).json()
        self.assertEqual(d["status"], "handoff_required")        # same copy-box UI as typing the command
        self.assertIn("oral rehydration solution", d["prompt_to_copy"])   # full prompt incl. the Question
        self.assertEqual(reg.calls[0][0], "generate_research_prompt")

    def test_discover_providers_reachable_from_plugin(self):   # M16.7 — manual trigger
        reg = _FakeReg()
        d = self._client(registry=reg).post(
            "/chat", json={"message": "vault:discover-providers"}).json()
        self.assertEqual(d["provider_used"], "system")          # handled directly, not via LLM
        self.assertIn("Discovery could not run", d["reply"])     # no vault_path in test config → graceful

    def test_ocr_command_reachable_from_plugin(self):         # M19 — vault:ocr via /chat
        import tempfile, threading as _t
        from fastapi.testclient import TestClient
        with tempfile.TemporaryDirectory() as d:
            from pathlib import Path as _P
            (_P(d) / "pic.png").write_bytes(b"\x89PNG")
            note = _P(d) / "n.md"; note.write_text("![[pic.png]]\n", encoding="utf-8")
            server = AssistantServer(
                router=_Router(), memory=None, registry=_FakeReg(), history=[],
                history_lock=_t.Lock(), config={"host": "127.0.0.1", "vault_path": d},
                system_prompt="SYS")
            # no multimodal provider + no tesseract → 0 read, but the sidecar is still written
            d2 = TestClient(server._app).post("/chat", json={"message": "vault:ocr n.md"}).json()
            self.assertEqual(d2["provider_used"], "system")
            self.assertIn("OCR:", d2["reply"])
            self.assertTrue((_P(d) / "AI" / "Derived" / "n.ocr.md").exists())

    def test_graph_endpoint_serves_subgraph(self):            # M18 — /graph
        import tempfile, threading as _t
        from fastapi.testclient import TestClient
        from assistant_core.graph.store import merge_triples
        with tempfile.TemporaryDirectory() as d:
            merge_triples(d, [("Rocket Heater", "uses", "Thermal Mass")], "n.md")
            server = AssistantServer(
                router=_Router(), memory=None, registry=_FakeReg(), history=[],
                history_lock=_t.Lock(), config={"host": "127.0.0.1", "vault_path": d}, system_prompt="S")
            r = TestClient(server._app).get("/graph", params={"node": "Rocket Heater", "depth": 1})
            self.assertEqual(r.status_code, 200)
            data = r.json()
            ids = {n["id"] for n in data["nodes"]}
            self.assertIn("Rocket Heater", ids)
            self.assertIn("Thermal Mass", ids)
            self.assertTrue(any(e["rel"] == "uses" for e in data["edges"]))

    def test_summarise_loads_note_then_summarises(self):      # T5.10
        import threading as _t
        from types import SimpleNamespace
        from fastapi.testclient import TestClient

        class _R:
            available_providers = ["groq"]
            def status(self): return {"groq": True}
            def generate(self, messages, system_prompt="", **kw):
                return "- Key fact one\n- Key fact two", "groq"      # the actual summary

        class _Reg:
            def __init__(self): self.calls = []
            def run(self, tool, inp):
                self.calls.append((tool, inp))
                return SimpleNamespace(success=True, output=f"NOTE CONTENT for {inp}",
                                       metadata={"path": inp})

        reg = _Reg()
        server = AssistantServer(
            router=_R(), memory=None, registry=reg, history=[],
            history_lock=_t.Lock(), config={"host": "127.0.0.1"}, system_prompt="S")
        d = TestClient(server._app).post(
            "/chat", json={"message": "vault:summarize AI/Research/x"}).json()
        self.assertEqual(reg.calls[0][0], "summarise_research")     # loaded via the tool
        self.assertIn("Key fact one", d["reply"])                   # summary, not raw note
        self.assertEqual(d["provider_used"], "groq")

    def test_webresearch_blocked_when_private(self):          # M21 — privacy hard-block
        import tempfile, threading as _t
        from pathlib import Path as _P
        from fastapi.testclient import TestClient
        with tempfile.TemporaryDirectory() as d:
            server = AssistantServer(
                router=_Router(), memory=None, registry=_FakeReg(), history=[],
                history_lock=_t.Lock(), config={"host": "127.0.0.1", "vault_path": d}, system_prompt="S")
            r = TestClient(server._app).post(
                "/chat", json={"message": "vault:webresearch rockets", "private": True}).json()
            self.assertEqual(r["provider_used"], "system")
            self.assertIn("private", r["reply"].lower())      # never touched the web
            self.assertEqual(list(_P(d).rglob("*.md")), [])   # nothing written

    def test_graph_entities_endpoint(self):                   # browse nodes without knowing names
        import tempfile, threading as _t
        from fastapi.testclient import TestClient
        from assistant_core.graph.store import merge_triples
        with tempfile.TemporaryDirectory() as d:
            merge_triples(d, [("Hub", "to", "A"), ("Hub", "to", "B")], "n.md")
            server = AssistantServer(
                router=_Router(), memory=None, registry=_FakeReg(), history=[],
                history_lock=_t.Lock(), config={"host": "127.0.0.1", "vault_path": d}, system_prompt="S")
            data = TestClient(server._app).get("/graph/entities").json()
            ids = [e["id"] for e in data["entities"]]
            self.assertIn("Hub", ids)
            self.assertEqual(ids[0], "Hub")                   # most-connected first

    def test_status_reports_providers(self):
        d = self._client().get("/status").json()
        self.assertTrue(d["online"])
        self.assertEqual(d["active_provider"], "groq")
        self.assertIn("groq", d["providers"])
        self.assertFalse(d["providers"]["google"])

    def test_history_filters_injected_noise(self):
        hist = [
            Message(role="user", content="hello"),
            Message(role="assistant", content="hi there"),
            Message(role="user", content="[Active note: foo.md]\n\ninjected context"),
            Message(role="assistant", content="Vault content loaded. Ready to help."),
        ]
        d = self._client(hist).get("/history").json()
        self.assertEqual(d["count"], 2)                       # only the real exchange survives
        contents = [m["content"] for m in d["messages"]]
        self.assertEqual(contents, ["hello", "hi there"])

    def test_handoff_return_injects_into_history(self):       # M7 T7.05 / T7.13
        client = self._client([])
        # the fake router has no generate(), so the optional summary step fails (expected)
        # and the raw pasted text is stored; capture the warning so it doesn't print.
        with self.assertLogs("assistant", level="WARNING"):
            r = client.post("/chat/handoff-return",
                            json={"response_text": "Here is the web answer.", "original_message": "q"})
        self.assertEqual(r.status_code, 200)
        hist = client.get("/history").json()
        self.assertTrue(any("Here is the web answer." in m["content"] for m in hist["messages"]))

    def test_handoff_return_empty_is_400(self):               # M7 T7.14
        self.assertEqual(
            self._client().post("/chat/handoff-return", json={"response_text": "   "}).status_code, 400)

    def test_handoff_return_saves_verbatim_then_summarises(self):   # M20 (hardened, T5.01)
        from fastapi.testclient import TestClient

        class _SummaryRouter:
            available_providers = ["groq"]
            def __init__(self): self.n = 0
            def status(self): return {"groq": True}
            def generate(self, messages, system_prompt="", **kw):
                self.n += 1                                          # exactly one call expected
                return "Rocket stoves burn wood very efficiently.", "groq"

        reg = _FakeReg()
        router = _SummaryRouter()
        server = AssistantServer(
            router=router, memory=None, registry=reg, history=[],
            history_lock=threading.Lock(), config={"host": "127.0.0.1"}, system_prompt="SYS",
        )
        r = TestClient(server._app).post("/chat/handoff-return", json={
            "response_text": "Rocket stoves burn wood efficiently.",
            "original_message": "how do rocket stoves work",
        })
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(reg.calls[0][0], "import_research")          # verbatim saved FIRST
        self.assertEqual(reg.calls[0][1], "Rocket stoves burn wood efficiently.")
        self.assertFalse(any(c[0] == "create_note" for c in reg.calls))  # NO agent loop / no fabrication
        self.assertEqual(router.n, 1)                                 # single non-agentic summary call
        self.assertIn("efficiently", d["reply"])                     # summary returned


@unittest.skipUnless(_fastapi_available, "fastapi/httpx not installed")
class ProactiveEndpointTests(unittest.TestCase):
    """M35.1 — /proactive apply/reject at whole-note AND per-item (tag/link) granularity,
    exercised through the exact HTTP contract the plugin panel calls."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        from assistant_core.proactive import organize
        from assistant_core import feedback
        self.organize, self.feedback = organize, feedback
        self.tmp = tempfile.mkdtemp()
        v = Path(self.tmp)
        (v / "Note.md").write_text("Body.\n", encoding="utf-8")
        (v / "Neighbour.md").write_text("x", encoding="utf-8")
        self._op, self._of = organize._PENDING_FILE, feedback._FILE
        organize._PENDING_FILE = v / "organize_pending.json"
        feedback._FILE = v / "feedback.json"
        organize._save_pending([{"note": "Note.md",
                                 "tags": ["faith", "prayer"], "related": ["Neighbour"]}])

    def tearDown(self):
        self.organize._PENDING_FILE = self._op
        self.feedback._FILE = self._of

    def _client(self):
        import threading
        from fastapi.testclient import TestClient
        server = AssistantServer(
            router=_Router(), memory=None, registry=_FakeReg(), history=[],
            history_lock=threading.Lock(),
            config={"host": "127.0.0.1", "vault_path": self.tmp}, system_prompt="S")
        return TestClient(server._app)

    def test_get_proactive_lists_pending(self):
        d = self._client().get("/proactive").json()
        self.assertEqual(d["proposals"][0]["note"], "Note.md")
        self.assertIn("faith", d["proposals"][0]["tags"])

    def test_apply_one_tag(self):
        from pathlib import Path
        c = self._client()
        r = c.post("/proactive/apply", json={"note": "Note.md", "tag": "faith"}).json()
        self.assertTrue(r["applied"])
        self.assertEqual(r["kind"], "tag")
        txt = (Path(self.tmp) / "Note.md").read_text(encoding="utf-8")
        self.assertIn("faith", txt)
        self.assertNotIn("prayer", txt)                       # only the one tag
        self.assertEqual(c.get("/proactive").json()["proposals"][0]["tags"], ["prayer"])

    def test_apply_one_link_adds_related(self):
        from pathlib import Path
        r = self._client().post("/proactive/apply", json={"note": "Note.md", "link": "Neighbour"}).json()
        self.assertTrue(r["applied"])
        self.assertIn("[[Neighbour]]", (Path(self.tmp) / "Note.md").read_text(encoding="utf-8"))

    def test_reject_one_records_feedback(self):
        r = self._client().post("/proactive/reject", json={"note": "Note.md", "tag": "prayer"}).json()
        self.assertTrue(r["rejected"])
        self.assertEqual(self.feedback.counts("tag", "prayer")["reject"], 1)
        self.assertEqual(self._client().get("/proactive").json()["proposals"][0]["tags"], ["faith"])

    def test_whole_note_apply_still_works(self):
        from pathlib import Path
        r = self._client().post("/proactive/apply", json={"note": "Note.md"}).json()
        self.assertTrue(r["applied"])
        txt = (Path(self.tmp) / "Note.md").read_text(encoding="utf-8")
        self.assertIn("faith", txt)
        self.assertIn("prayer", txt)                          # whole-note = all tags
        self.assertEqual(self._client().get("/proactive").json()["proposals"], [])


@unittest.skipUnless(_fastapi_available, "fastapi/httpx not installed")
class ApprovalsEndpointTests(unittest.TestCase):
    """M36 — GET /approvals + POST /approvals/{apply,reject} over the HTTP contract."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        from assistant_core.proactive import organize
        from assistant_core import feedback
        self.organize, self.feedback = organize, feedback
        self.tmp = tempfile.mkdtemp()
        v = Path(self.tmp)
        (v / "Note.md").write_text("Body.\n", encoding="utf-8")
        (v / "Neighbour.md").write_text("x", encoding="utf-8")
        self._op, self._of = organize._PENDING_FILE, feedback._FILE
        organize._PENDING_FILE = v / "organize_pending.json"
        feedback._FILE = v / "feedback.json"
        organize._save_pending([{"note": "Note.md", "tags": ["faith"], "related": ["Neighbour"]}])

    def tearDown(self):
        self.organize._PENDING_FILE = self._op
        self.feedback._FILE = self._of

    def _client(self):
        import threading
        from fastapi.testclient import TestClient
        server = AssistantServer(
            router=_Router(), memory=None, registry=_FakeReg(), history=[],
            history_lock=threading.Lock(),
            config={"host": "127.0.0.1", "vault_path": self.tmp}, system_prompt="S")
        return TestClient(server._app)

    def test_list_and_apply_one(self):
        from pathlib import Path
        c = self._client()
        d = c.get("/approvals").json()
        org = next(a for a in d["approvals"] if a["kind"] == "organize")
        self.assertEqual(org["id"], "organize:Note.md")
        tag_item = next(i for i in org["items"] if i["itemkind"] == "tag")
        r = c.post("/approvals/apply", json={"id": "organize:Note.md", "item": tag_item}).json()
        self.assertTrue(r["applied"])
        self.assertIn("faith", (Path(self.tmp) / "Note.md").read_text(encoding="utf-8"))

    def test_reject_requires_id(self):
        self.assertEqual(self._client().post("/approvals/reject", json={}).status_code, 400)


@unittest.skipUnless(_fastapi_available, "fastapi/httpx not installed")
class ContradictionsEndpointTests(unittest.TestCase):
    """M37 — vault:contradictions runs the deterministic detector via /chat (provider=system)."""

    def test_vault_contradictions_reports(self):
        import tempfile, threading
        from pathlib import Path
        from fastapi.testclient import TestClient
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "a.md").write_text(
                "The annual conference attendance reached 5000 registered members.", encoding="utf-8")
            (Path(d) / "b.md").write_text(
                "The annual conference attendance reached 8000 registered members.", encoding="utf-8")
            server = AssistantServer(
                router=_Router(), memory=None, registry=_FakeReg(), history=[],
                history_lock=threading.Lock(),
                config={"host": "127.0.0.1", "vault_path": d}, system_prompt="S")
            r = TestClient(server._app).post("/chat", json={"message": "vault:contradictions"}).json()
            self.assertEqual(r["provider_used"], "system")
            self.assertIn("contradiction", r["reply"].lower())


if __name__ == "__main__":
    unittest.main()
