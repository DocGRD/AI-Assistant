"""M21 — web-capable research (search / fetch / autonomous). Stdlib unittest, no network."""

import tempfile
import unittest
from pathlib import Path

from assistant_core.web.search import web_search, _decode_ddg
from assistant_core.web.fetch import web_fetch, html_to_text
from assistant_core.web.research import run_web_research, _slugify


class SearchTests(unittest.TestCase):
    def test_injected_search_fn(self):
        out = web_search("rockets", k=2, search_fn=lambda q, k: [
            {"title": "A", "url": "https://a.com", "snippet": "sa"},
            {"title": "B", "url": "https://b.com", "snippet": "sb"}])
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["url"], "https://a.com")

    def test_empty_query_and_failure_are_safe(self):
        self.assertEqual(web_search("  "), [])
        # a failing search_fn is caught → []; capture the warning so it doesn't print.
        with self.assertLogs("assistant", level="WARNING"):
            self.assertEqual(
                web_search("x", search_fn=lambda q, k: (_ for _ in ()).throw(RuntimeError())), [])

    def test_ddg_redirect_decode(self):
        u = _decode_ddg("//duckduckgo.com/l/?uddg=https%3A%2F%2Fen.wikipedia.org%2Fwiki%2FRocket")
        self.assertEqual(u, "https://en.wikipedia.org/wiki/Rocket")


class ProviderRegistryTests(unittest.TestCase):
    def test_skips_unconfigured_and_falls_through_in_order(self):
        from assistant_core.web import providers as P
        calls = []
        def mk(name, result):
            def _fn(q, k, c): calls.append(name); return result
            return _fn
        # brave has no key -> skipped; serper fails; tavily returns.
        saved = dict(P.PROVIDERS)
        try:
            P.PROVIDERS.update({
                "brave":  (mk("brave", [{"title": "b", "url": "https://b", "snippet": ""}]),
                           lambda c: bool(c.get("brave_api_key"))),
                "serper": (mk("serper", (_ for _ in ()).throw(RuntimeError()) if False else None),
                           lambda c: True),
                "tavily": (mk("tavily", [{"title": "t", "url": "https://t", "snippet": ""}]),
                           lambda c: True),
            })
            def _serper_fail(q, k, c): calls.append("serper"); raise RuntimeError("boom")
            P.PROVIDERS["serper"] = (_serper_fail, lambda c: True)
            with self.assertLogs("assistant", level="WARNING"):   # serper failure is expected
                out = web_search("q", k=3, config={"web_search_order": ["brave", "serper", "tavily"]})
            self.assertEqual(out[0]["url"], "https://t")     # tavily won
            self.assertEqual(calls, ["serper", "tavily"])    # brave skipped (no key), serper failed
        finally:
            P.PROVIDERS.clear(); P.PROVIDERS.update(saved)

    def test_default_order_is_keyless_first(self):
        from assistant_core.web.providers import DEFAULT_ORDER
        self.assertEqual(DEFAULT_ORDER[0], "duckduckgo")


class FetchTests(unittest.TestCase):
    def test_html_to_text_strips_scripts_and_tags(self):
        html = "<html><head><title>T</title><script>bad()</script></head><body><p>Hello</p><p>World</p></body></html>"
        text = html_to_text(html)
        self.assertIn("Hello", text)
        self.assertIn("World", text)
        self.assertNotIn("bad()", text)
        self.assertNotIn("<p>", text)

    def test_fetch_with_injected_fn(self):
        page = web_fetch("https://x.com", fetch_fn=lambda u: "<title>Doc</title><body><p>Body text</p></body>")
        self.assertTrue(page["ok"])
        self.assertEqual(page["title"], "Doc")
        self.assertIn("Body text", page["text"])

    def test_bad_url_and_failure_are_safe(self):
        self.assertFalse(web_fetch("not-a-url")["ok"])
        with self.assertLogs("assistant", level="WARNING"):
            self.assertFalse(
                web_fetch("https://x.com", fetch_fn=lambda u: (_ for _ in ()).throw(IOError()))["ok"])


class _Router:
    """Fake router: a clean title when asked for one, else a cited synthesis."""
    def __init__(self): self.private_calls = 0
    def generate(self, messages, system_prompt="", private=False, **kw):
        if private:
            self.private_calls += 1
        if "title" in system_prompt.lower():
            return "Rocket Mass Heater", "groq"
        return "Rocket mass heaters store heat in thermal mass [1] and burn cleanly [2].", "groq"


def _search(query, k):
    return [{"title": "Wiki RMH", "url": "https://en.wikipedia.org/wiki/RMH", "snippet": "s"},
            {"title": "Insteading", "url": "https://insteading.com/rmh", "snippet": "s2"}]

def _fetch(url):
    return f"<title>Page {url}</title><body><p>Content about rocket mass heaters from {url}.</p></body>"


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = self._tmp.name
        self.cfg = {"vault_path": self.vault, "web_research_enabled": True, "web_max_fetches": 2}

    def tearDown(self):
        self._tmp.cleanup()

    def test_saves_summary_and_verbatim_sources_with_citations(self):
        rep = run_web_research("how do rocket mass heaters work", _Router(), self.cfg,
                               search_fn=_search, fetch_fn=_fetch)
        self.assertIsNone(rep["error"])
        self.assertEqual(len(rep["sources"]), 2)
        summary = (Path(self.vault) / rep["summary_path"]).read_text(encoding="utf-8")
        self.assertIn("thermal mass [1]", summary)          # synthesis with citations
        self.assertIn("## Sources", summary)
        self.assertIn("https://en.wikipedia.org/wiki/RMH", summary)
        # each fetched page saved verbatim in the folder
        src1 = Path(self.vault) / rep["sources"][0]["file"]
        self.assertTrue(src1.exists())
        self.assertIn("Content about rocket mass heaters", src1.read_text(encoding="utf-8"))
        self.assertIn("rocket-mass-heater", rep["summary_path"])   # LLM title slug

    def test_private_turn_is_blocked_from_web(self):
        rep = run_web_research("q", _Router(), self.cfg, search_fn=_search, fetch_fn=_fetch, private=True)
        self.assertIn("private", rep["error"])
        self.assertIsNone(rep["summary_path"])
        self.assertEqual(list(Path(self.vault).rglob("*.md")), [])   # nothing written

    def test_disabled_and_no_results(self):
        off = run_web_research("q", _Router(), {**self.cfg, "web_research_enabled": False}, search_fn=_search)
        self.assertIn("disabled", off["error"])
        empty = run_web_research("q", _Router(), self.cfg, search_fn=lambda q, k: [])
        self.assertIn("no web results", empty["error"])

    def test_slugify(self):
        self.assertEqual(_slugify("Rocket Mass Heater!"), "rocket-mass-heater")


if __name__ == "__main__":
    unittest.main()
