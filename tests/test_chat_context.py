"""
Tests for Milestone 9 Slice 1 — active-note + selection context injection on /chat.

Stdlib unittest + FastAPI TestClient. No network, no real provider: a fake router
captures the message the agent loop would send so we can assert what was injected.

Run with:
    python -m unittest tests.test_chat_context -v
"""

import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from assistant_core.providers.model_registry import ModelRegistry
from assistant_core.server import AssistantServer, _fastapi_available


class _FakeToolRegistry:
    """Minimal ToolRegistry: read_note returns deterministic content."""
    def run(self, tool_name, input_data=""):
        if tool_name == "read_note":
            return SimpleNamespace(success=True, output=f"BODY OF {input_data}")
        return SimpleNamespace(success=False, output="unknown tool")


class _FakeRouter:
    """Captures the messages the agent loop passes to generate(); no network."""
    def __init__(self, edit_reply="REVISED TEXT", raise_on_edit=False):
        self.registry = ModelRegistry({})          # hardcoded specs, no vault
        self.available_providers = ["groq"]
        self.captured_last_message = None
        self.captured_private = None
        self.captured_allow_webui = None
        self._edit_reply = edit_reply
        self._raise_on_edit = raise_on_edit

    def generate(self, messages, system_prompt="", max_tokens=2048, temperature=0.7,
                 provider_override=None, private=False, allow_webui_on_private=False,
                 allow_webui=True):
        self.captured_last_message = messages[-1].content if messages else ""
        self.captured_private = private
        self.captured_allow_webui = allow_webui
        # The edit flow calls with allow_webui=False; simulate exhaustion when asked.
        if not allow_webui and self._raise_on_edit:
            from assistant_core.providers.base_provider import ProviderError
            raise ProviderError("all providers failed")
        if not allow_webui:
            return self._edit_reply, "groq"
        return "OK", "groq"


def _make_client(router, config=None):
    from fastapi.testclient import TestClient
    server = AssistantServer(
        router        = router,
        memory        = None,
        registry      = _FakeToolRegistry(),
        history       = [],
        history_lock  = threading.Lock(),
        config        = config or {"host": "127.0.0.1", "port": 8765},
        system_prompt = "SYS",
    )
    return TestClient(server._app)


@unittest.skipUnless(_fastapi_available, "fastapi/httpx not installed")
class ApiTokenTests(unittest.TestCase):
    def test_token_required_when_configured(self):
        client = _make_client(_FakeRouter(), {"host": "0.0.0.0", "port": 8765, "api_token": "secret"})
        # no header → 401
        self.assertEqual(client.post("/chat", json={"message": "hi"}).status_code, 401)
        # wrong header → 401
        self.assertEqual(
            client.post("/chat", json={"message": "hi"}, headers={"X-API-Key": "nope"}).status_code, 401)
        # right header → ok
        self.assertEqual(
            client.post("/chat", json={"message": "hi"}, headers={"X-API-Key": "secret"}).status_code, 200)

    def test_no_token_means_open(self):
        client = _make_client(_FakeRouter())   # no api_token
        self.assertEqual(client.post("/chat", json={"message": "hi"}).status_code, 200)


class _FakeRag:
    """Minimal RagService stand-in for the Vault QA server path."""
    def __init__(self, hits):
        self._hits = hits
    def has_index(self):
        return bool(self._hits)
    def retriever(self):
        from assistant_core.rag.retriever import Retriever
        rag = self
        class _R:
            def retrieve(self, q, k=6, scope=None):
                return rag._hits
            def build_context(self, hits):
                return "\n".join(f"[Source: {h.citation()}]\n{h.text}" for h in hits)
        return _R()


@unittest.skipUnless(_fastapi_available, "fastapi/httpx not installed")
class VaultQAServerTests(unittest.TestCase):
    def _client_with_rag(self, hits):
        from fastapi.testclient import TestClient
        server = AssistantServer(
            router=_FakeRouter(), memory=None, registry=_FakeToolRegistry(),
            history=[], history_lock=threading.Lock(),
            config={"host": "127.0.0.1", "port": 8765}, system_prompt="SYS",
            rag=_FakeRag(hits),
        )
        return TestClient(server._app)

    def test_vault_qa_returns_answer_and_sources(self):
        from assistant_core.rag.retriever import Hit
        hits = [Hit(0.9, "notes/a.md", "Intro", "alpha text", False),
                Hit(0.8, "notes/b.md", "", "beta text", False)]
        client = self._client_with_rag(hits)
        resp = client.post("/chat", json={"message": "what is alpha?", "vault_qa": True})
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertTrue(data["reply"])                              # grounded answer present
        self.assertEqual(data["sources"], ["notes/a.md#Intro", "notes/b.md"])  # cited sources

    def test_vault_qa_no_index(self):
        client = self._client_with_rag([])
        resp = client.post("/chat", json={"message": "x", "vault_qa": True})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIn("No vault index", resp.json()["reply"])


@unittest.skipUnless(_fastapi_available, "fastapi/httpx not installed")
class RelevantEndpointTests(unittest.TestCase):
    def test_relevant_returns_notes(self):
        from fastapi.testclient import TestClient

        class _Rag:
            def has_index(self): return True
            def relevant_notes(self, path, k=5): return [{"path": "b.md", "score": 0.9}]
        server = AssistantServer(
            router=_FakeRouter(), memory=None, registry=_FakeToolRegistry(),
            history=[], history_lock=threading.Lock(),
            config={"host": "127.0.0.1", "port": 8765}, system_prompt="SYS", rag=_Rag(),
        )
        client = TestClient(server._app)
        data = client.get("/relevant?path=a.md").json()
        self.assertEqual(data["notes"], [{"path": "b.md", "score": 0.9}])

    def test_relevant_no_index_empty(self):
        from fastapi.testclient import TestClient
        server = AssistantServer(
            router=_FakeRouter(), memory=None, registry=_FakeToolRegistry(),
            history=[], history_lock=threading.Lock(),
            config={"host": "127.0.0.1", "port": 8765}, system_prompt="SYS", rag=None,
        )
        client = TestClient(server._app)
        self.assertEqual(client.get("/relevant?path=a.md").json(), {"notes": []})


@unittest.skipUnless(_fastapi_available, "fastapi/httpx not installed")
class ChatContextInjectionTests(unittest.TestCase):

    def setUp(self):
        self.router = _FakeRouter()
        self.client = _make_client(self.router)

    def test_active_note_and_selection_are_injected(self):
        resp = self.client.post("/chat", json={
            "message": "What does this say?",
            "active_note_path": "AI/Notes/foo.md",
            "selection": {
                "text": "The quick brown fox.",
                "from": {"line": 1, "ch": 0},
                "to":   {"line": 1, "ch": 20},
                "scope": "paragraph",
            },
        })
        self.assertEqual(resp.status_code, 200, resp.text)
        sent = self.router.captured_last_message
        self.assertIn("[Active note: AI/Notes/foo.md]", sent)
        self.assertIn("BODY OF AI/Notes/foo.md", sent)        # whole-note context
        self.assertIn("[Selected text — paragraph]", sent)     # selection label + scope
        self.assertIn("> The quick brown fox.", sent)          # selection quoted
        self.assertIn("What does this say?", sent)             # original message preserved
        # Framing: injected context is labelled BACKGROUND and the user's message is
        # clearly the request — so the model doesn't mistake the open note for pasted input.
        self.assertIn("=== BACKGROUND", sent)
        self.assertIn("=== USER MESSAGE (respond to THIS) ===", sent)
        self.assertLess(sent.index("=== BACKGROUND"), sent.index("=== USER MESSAGE"))
        # the message comes after the background marker
        self.assertGreater(sent.index("What does this say?"), sent.index("=== USER MESSAGE"))

    def test_plain_message_unaffected(self):
        resp = self.client.post("/chat", json={"message": "hello"})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(self.router.captured_last_message, "hello")  # no injection when no context

    def test_selection_without_active_note(self):
        resp = self.client.post("/chat", json={
            "message": "define this",
            "selection": {"text": "epistemology", "scope": "word"},
        })
        self.assertEqual(resp.status_code, 200, resp.text)
        sent = self.router.captured_last_message
        self.assertIn("[Selected text — word]", sent)
        self.assertIn("> epistemology", sent)
        self.assertNotIn("[Active note:", sent)


@unittest.skipUnless(_fastapi_available, "fastapi/httpx not installed")
class MentionsTests(unittest.TestCase):
    def test_mentions_injected(self):
        router = _FakeRouter()
        client = _make_client(router)
        resp = client.post("/chat", json={"message": "summarize", "mentions": ["notes/a.md", "notes/b.md"]})
        self.assertEqual(resp.status_code, 200, resp.text)
        sent = router.captured_last_message
        self.assertIn("[Mentioned note: notes/a.md]", sent)
        self.assertIn("BODY OF notes/a.md", sent)
        self.assertIn("[Mentioned note: notes/b.md]", sent)
        self.assertIn("summarize", sent)

    def test_project_memory_injected(self):
        tmp = tempfile.mkdtemp()
        (Path(tmp) / "note.md").write_text("---\nproject: rocket\n---\n\nbody text", encoding="utf-8")
        router = _FakeRouter()
        client = _make_client(router, {"host": "127.0.0.1", "port": 8765, "vault_path": tmp})
        resp = client.post("/chat", json={"message": "help", "active_note_path": "note.md"})
        self.assertEqual(resp.status_code, 200, resp.text)
        sent = router.captured_last_message
        self.assertIn("[Project memory: rocket]", sent)
        self.assertIn("BODY OF AI/Memory/Projects/rocket.md", sent)   # project file read

    def test_private_mention_forces_private(self):
        tmp = tempfile.mkdtemp()
        (Path(tmp) / "sec.md").write_text("---\nprivate: true\n---\n\nsecret stuff", encoding="utf-8")
        router = _FakeRouter()
        client = _make_client(router, {"host": "127.0.0.1", "port": 8765, "vault_path": tmp})
        resp = client.post("/chat", json={"message": "x", "mentions": ["sec.md"]})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(router.captured_private)   # private source → no-train routing


@unittest.skipUnless(_fastapi_available, "fastapi/httpx not installed")
class EditFlowTests(unittest.TestCase):

    def test_edit_returns_a_proposal(self):
        router = _FakeRouter(edit_reply="```\nThe quick brown fox jumps.\n```")  # fenced → cleaned
        client = _make_client(router)
        resp = client.post("/chat", json={
            "message": "make it a full sentence",
            "edit": True,
            "active_note_path": "AI/Notes/foo.md",
            "selection": {
                "text": "the quick brown fox",
                "from": {"line": 2, "ch": 0},
                "to":   {"line": 2, "ch": 19},
                "scope": "paragraph",
            },
        })
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        prop = data["proposal"]
        self.assertIsNotNone(prop)
        self.assertEqual(prop["scope"], "paragraph")
        self.assertEqual(prop["original_text"], "the quick brown fox")
        self.assertEqual(prop["replacement"], "The quick brown fox jumps.")  # fence stripped
        self.assertEqual(prop["offsets"], {"from": {"line": 2, "ch": 0}, "to": {"line": 2, "ch": 19}})
        # The edit path must NOT allow the chat webui fallback.
        self.assertFalse(router.captured_allow_webui)

    def test_word_scope_returns_parsed_options(self):
        # Reply with numbering/bullets/quotes + a fence → parsed to clean options.
        router = _FakeRouter(edit_reply="```\n1. swift\n- rapid\n\"speedy\"\nswift\n```")
        client = _make_client(router)
        resp = client.post("/chat", json={
            "message": "synonyms for fast",
            "edit": True,
            "selection": {
                "text": "quick",
                "from": {"line": 0, "ch": 4},
                "to":   {"line": 0, "ch": 9},
                "scope": "word",
            },
        })
        self.assertEqual(resp.status_code, 200, resp.text)
        prop = resp.json()["proposal"]
        self.assertEqual(prop["options"], ["swift", "rapid", "speedy"])  # cleaned + deduped
        self.assertEqual(prop["replacement"], "swift")                    # default = first option

    def test_edit_without_selection_is_400(self):
        client = _make_client(_FakeRouter())
        resp = client.post("/chat", json={"message": "fix it", "edit": True})
        self.assertEqual(resp.status_code, 400, resp.text)

    def test_edit_exhaustion_returns_edit_handoff(self):
        router = _FakeRouter(raise_on_edit=True)
        client = _make_client(router)
        with self.assertLogs("assistant", level="WARNING"):   # provider exhaustion is expected
            resp = client.post("/chat", json={
                "message": "tighten this",
                "edit": True,
                "selection": {"text": "some prose", "scope": "section"},
            })
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertEqual(data["status"], "edit_handoff_required")
        self.assertIn("Region to revise", data["prompt_to_copy"])
        self.assertIsNone(data["proposal"])


@unittest.skipUnless(_fastapi_available, "fastapi/httpx not installed")
class SettingsApiTests(unittest.TestCase):
    """M16.5 — /settings read/write + /restart guard (the plugin control panel)."""

    def _client(self, config, settings_path):
        from fastapi.testclient import TestClient
        server = AssistantServer(
            router=_FakeRouter(), memory=None, registry=_FakeToolRegistry(),
            history=[], history_lock=threading.Lock(), config=config,
            system_prompt="SYS", settings_path=settings_path,
        )
        return TestClient(server._app), server

    def test_get_redacts_secrets(self):
        cfg = {"host": "127.0.0.1", "max_agent_steps": 10,
               "groq_api_key": "gsk_secret", "api_token": ""}
        client, _ = self._client(cfg, "ignored.json")
        s = client.get("/settings").json()["settings"]
        self.assertEqual(s["groq_api_key"], "********")   # set → masked
        self.assertEqual(s["api_token"], "")              # empty → empty
        self.assertEqual(s["max_agent_steps"], 10)        # non-secret passes through

    def test_put_writes_file_and_live_applies(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "settings.json"
            path.write_text('{"max_agent_steps": 10, "port": 8765}', encoding="utf-8")
            cfg = {"host": "127.0.0.1", "max_agent_steps": 10, "port": 8765}
            client, server = self._client(cfg, path)

            res = client.put("/settings", json={"max_agent_steps": 4, "port": 9000}).json()
            self.assertTrue(res["ok"])
            self.assertIn("max_agent_steps", res["updated"])
            self.assertEqual(res["restart_required"], ["port"])   # port needs a restart
            # max_agent_steps is live → the in-memory config the request path reads is updated
            self.assertEqual(server._config["max_agent_steps"], 4)
            # both persisted to disk
            disk = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual((disk["max_agent_steps"], disk["port"]), (4, 9000))

    def test_put_keeps_secret_on_blank_or_placeholder(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "settings.json"
            path.write_text('{"groq_api_key": "gsk_real"}', encoding="utf-8")
            client, _ = self._client({"host": "127.0.0.1", "groq_api_key": "gsk_real"}, path)
            client.put("/settings", json={"groq_api_key": "********"})
            self.assertEqual(json.loads(path.read_text())["groq_api_key"], "gsk_real")
            client.put("/settings", json={"groq_api_key": ""})
            self.assertEqual(json.loads(path.read_text())["groq_api_key"], "gsk_real")
            client.put("/settings", json={"groq_api_key": "gsk_new"})
            self.assertEqual(json.loads(path.read_text())["groq_api_key"], "gsk_new")

    def test_get_surfaces_all_schema_keys_even_when_unset(self):
        # Only host is in the live config; the panel must still show key slots +
        # provider_sources from the schema (settings.example.json) so they're enterable.
        client, _ = self._client({"host": "127.0.0.1"}, "ignored.json")
        s = client.get("/settings").json()["settings"]
        self.assertIn("nvidia_api_key", s)          # key slot present even if never set
        self.assertEqual(s["nvidia_api_key"], "")    # unset secret → empty (enterable)
        self.assertIn("provider_sources", s)
        self.assertIsInstance(s["provider_sources"], list)

    def test_admin_blocked_when_public_and_unauthenticated(self):
        client, _ = self._client({"host": "0.0.0.0", "api_token": ""}, "x.json")
        self.assertEqual(client.put("/settings", json={"max_tokens": 1}).status_code, 403)
        self.assertEqual(client.post("/restart").status_code, 403)
        self.assertFalse(client.get("/settings").json()["admin_allowed"])


if __name__ == "__main__":
    unittest.main()
