"""
HTTP Server — Milestone 8 refactor

Key change: POST /chat/handoff-return now runs the pasted web AI
response through the agent loop before storing it as the final answer.

Why: Web AIs reading the WebUI-Prompt.md instructions will say things
like "you may want to search your vault for X" in plain English. The
agent loop scans for vault: commands in the response — but the web AI
is now told NOT to emit vault commands. So instead this endpoint does
something smarter: it looks for the phrase "search your vault for" and
similar patterns, converts them into actual vault commands, executes
them, and packages the enriched result ready for another handoff round.

This makes the handoff a genuine research loop:
  1. User asks question
  2. Web AI answers + suggests a vault search
  3. System executes the search automatically
  4. User sees: web AI answer + actual vault search results
  5. User can send the enriched context back to the web AI

Other changes:
  - vault_path passed into AssistantServer so webui_provider can load
    WebUI-Prompt.md
  - /shutdown endpoint preserved from headless-fixes patch
  - exit/quit intercept preserved
  - All history filtering updated to strip new noise prefixes
"""

import json
import logging
import os
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from assistant_core import editing   # M9 — shared edit helpers (prompts, cleaning, proposal building)
from assistant_core.paths import CONFIG_DIR
from assistant_core.server.models import _fastapi_available
from assistant_core.server.suggestions import extract_vault_suggestions

logger = logging.getLogger("assistant")

# M16.5 — settings that take effect immediately (read per-request from the live
# config dict). Everything else needs a restart (providers, binds, embedding,
# vault path are wired at startup).
LIVE_SETTING_KEYS = {
    "max_agent_steps", "max_tokens", "temperature", "log_level",
    "hybrid_retrieval", "hybrid_weights", "hybrid_depth",
}


def _is_secret(key: str) -> bool:
    return key == "api_token" or key.endswith("_api_key")

if _fastapi_available:
    import uvicorn
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
    from assistant_core.server.models import (
        ChatRequest, HandoffResponse, HandoffReturnRequest,
        HistoryMessage, StatusResponse, HistoryResponse, MemoryApplyRequest,
    )


# ---------------------------------------------------------------------------
# Server class
# ---------------------------------------------------------------------------

class AssistantServer:

    def __init__(
        self,
        router,
        memory,
        registry,
        history:        list,
        history_lock:   threading.Lock,
        config:         dict,
        system_prompt:  str             = "",
        ep_chat_fn                      = None,
        ep_error_fn                     = None,
        ep_handoff_fn                   = None,
        ep_vault_fn                     = None,
        shutdown_event: threading.Event | None = None,
        rag                             = None,   # M11 — RagService | None
        settings_path                   = None,   # M16.5 — where /settings writes (tests inject)
    ):
        self._settings_path  = Path(settings_path) if settings_path else CONFIG_DIR / "settings.json"
        self._router         = router
        self._memory         = memory
        self._registry       = registry
        self._rag            = rag
        self._history        = history
        self._history_lock   = history_lock
        self._config         = config
        self._system_prompt  = system_prompt
        self._ep_chat        = ep_chat_fn
        self._ep_error       = ep_error_fn
        self._ep_handoff     = ep_handoff_fn
        self._ep_vault       = ep_vault_fn
        self._shutdown_event = shutdown_event
        self._host           = config.get("host",  "127.0.0.1")
        self._port           = config.get("port",  8765)
        self._api_token      = str(config.get("api_token", "")).strip()   # LAN auth (empty = off)
        self._session_start  = datetime.now().strftime("%Y-%m-%d %H:%M")
        self._thread         = None
        self._server         = None
        self._provider_override: str | None = None

        if not _fastapi_available:
            logger.warning("[Server] FastAPI/uvicorn not installed.")
            return

        self._app = self._build_app()

    def start(self) -> None:
        if not _fastapi_available:
            print("[HTTP server disabled — run: pip install fastapi uvicorn[standard]]\n")
            return

        cfg = uvicorn.Config(
            app        = self._app,
            host       = self._host,
            port       = self._port,
            log_level  = "warning",
            loop       = "asyncio",
            access_log = False,
        )
        self._server = uvicorn.Server(cfg)
        self._thread = threading.Thread(
            target = self._server.run,
            daemon = True,
            name   = "AssistantHTTPServer",
        )
        self._thread.start()
        logger.info(f"[Server] HTTP server started on http://{self._host}:{self._port}")

        # M35 — start the goal worker (background, governor-paced) unless disabled.
        if self._config.get("goals_enabled", True):
            try:
                from assistant_core.goals.worker import GoalWorker
                self._goal_worker = GoalWorker(
                    self._config.get("vault_path"), self._config, self._run_goal_subtask,
                    tick_seconds=int(self._config.get("goal_tick_seconds", 60)))
                self._goal_worker.start()
            except Exception as exc:
                logger.warning(f"[Goals] worker not started: {exc}")

        if self._host in ("0.0.0.0", "::"):
            auth = " (X-API-Key required)" if self._api_token else " — NO AUTH; set api_token in settings"
            print(f"[HTTP API active — local: http://127.0.0.1:{self._port} | "
                  f"LAN: http://{self._lan_ip()}:{self._port}{auth}]\n")
        else:
            print(f"[HTTP API active on http://{self._host}:{self._port}]\n")

    @staticmethod
    def _lan_ip() -> str:
        """Best-effort primary LAN IP (no packets actually sent)."""
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def _run_goal_subtask(self, instruction: str) -> str:
        """M35 — run one goal subtask as an autonomous agent turn (full command access)."""
        import threading as _th
        from assistant_core.agent_loop import AgentContext, run_agent_loop
        ctx = AgentContext(
            user_input=instruction, history=[], history_lock=_th.Lock(),
            router=self._router, registry=self._registry, memory=self._memory,
            ctx_mgr=None, system_prompt=self._system_prompt,
            max_tokens=int(self._config.get("max_tokens", 4096)),
            config=self._config, rag=self._rag,
            max_steps=int(self._config.get("max_agent_steps", 10)),
            source_label="goal", ep_vault_fn=self._ep_vault,
        )
        reply, _ = run_agent_loop(ctx)
        return reply

    def stop(self) -> None:
        if getattr(self, "_goal_worker", None):
            self._goal_worker.stop()
        if self._server:
            self._server.should_exit = True
            logger.info("[Server] HTTP server stopping")

    def is_available(self) -> bool:
        return _fastapi_available

    # ------------------------------------------------------------------
    # M9 — edit flow (propose/commit). Bypasses the agent loop on purpose:
    # deterministic single-shot generation, no history, no vault: commands.
    # The model only ever proposes; the plugin commits.
    # ------------------------------------------------------------------

    def _handle_edit(self, req) -> "HandoffResponse":
        from assistant_core.providers.base_provider import Message, ProviderError, ProviderWebUIHandoff

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sel = req.selection if isinstance(req.selection, dict) else None
        if not sel or not sel.get("text"):
            raise HTTPException(status_code=400, detail="An edit requires a selected region.")

        original = sel["text"]
        scope    = sel.get("scope") or req.scope or "selection"
        # Privacy: honor the request flag OR force it from the note's frontmatter (M10 + decision Q5).
        private  = bool(req.private) or self._note_is_private(req.active_note_path)

        override = req.provider_override
        if override in (None, "auto"):
            override = None

        is_word   = scope == "word"
        edit_sys  = editing.EDIT_WORD_SYSTEM if is_word else editing.EDIT_SYSTEM
        user_body = (f"Instruction: {req.message}\n\nWord/phrase: {original}" if is_word
                     else f"Instruction: {req.message}\n\nRegion to revise:\n{original}")
        logger.info(f"[Server] /chat edit — scope={scope} private={private} ({len(original)} chars)")

        options: list[str] = []
        sections = 1
        # M31 — a large selection would truncate in one capped call; split it, edit each
        # section, reassemble into one proposal.
        if (not is_word) and len(original) > editing.EDIT_CHUNK_CHARS:
            chunks   = editing.split_for_edit(original)
            sections = len(chunks)
            logger.info(f"[Server] Large edit — splitting into {sections} sections")
            edited: list[str] = []
            used = None
            for i, ch in enumerate(chunks):
                body = f"Instruction: {req.message}\n\nRegion to revise:\n{ch}"
                try:
                    rep, used = self._router.generate(
                        [Message(role="user", content=body)], system_prompt=edit_sys,
                        max_tokens=req.max_tokens, temperature=req.temperature,
                        provider_override=override, private=private, allow_webui=False,
                        task="edit",
                    )
                    edited.append(editing.clean_edit_reply(rep))
                except (ProviderError, ProviderWebUIHandoff) as exc:
                    if i == 0:                       # nothing usable — hand off as before
                        logger.warning(f"[Server] Edit providers exhausted: {exc}")
                        return self._edit_handoff_response(req, original, private, ts)
                    logger.warning(f"[Server] Edit section {i+1}/{sections} failed ({exc}); keeping original")
                    edited.append(ch)
            replacement = "\n\n".join(edited)
        else:
            messages = [Message(role="user", content=user_body)]
            try:
                reply, used = self._router.generate(
                    messages, system_prompt=edit_sys,
                    max_tokens=req.max_tokens, temperature=req.temperature,
                    provider_override=override, private=private, allow_webui=False,
                    task="edit",
                )
            except (ProviderError, ProviderWebUIHandoff) as exc:
                logger.warning(f"[Server] Edit providers exhausted: {exc}")
                return self._edit_handoff_response(req, original, private, ts)
            if is_word:
                options     = editing.parse_options(reply)
                replacement = options[0] if options else editing.clean_edit_reply(reply)
            else:
                replacement = editing.clean_edit_reply(reply)

        offsets  = {"from": sel.get("from"), "to": sel.get("to")}
        proposal = editing.make_proposal(
            note_path=req.active_note_path, scope=scope, intent=req.message,
            original_text=original, replacement=replacement, options=options,
            offsets=offsets, source="live", provider=used,
        )
        if self._memory and self._ep_vault:
            self._memory.append_episode(self._ep_vault("propose_edit", f"{scope} on {req.active_note_path} [plugin]"))
        reply_msg = ("Proposed edit ready — review and Replace." if sections == 1
                     else f"Proposed edit ready ({sections} sections) — review and Replace.")
        return HandoffResponse(
            status="ok", reply=reply_msg,
            provider_used=used, actual_provider=used, timestamp=ts, proposal=proposal,
        )

    def _handle_vault_qa(self, req) -> "HandoffResponse":
        """M11 — retrieve from the vault index and answer with cited sources (no agent loop)."""
        from assistant_core.providers.base_provider import ProviderError, ProviderWebUIHandoff
        from assistant_core.rag.qa import run_vault_qa

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not self._rag or not self._rag.has_index():
            return HandoffResponse(
                status="ok", provider_used="system", actual_provider="system", timestamp=ts,
                reply="No vault index is available yet — run `vault:reindex` on the indexing host.",
                sources=[],
            )
        scope = {}
        if req.scope_folder:
            scope["folder"] = req.scope_folder
        if req.scope_tag:
            scope["tag"] = req.scope_tag
        try:
            res = run_vault_qa(
                self._router, self._rag.retriever(), req.message,
                force_private=bool(req.private), max_tokens=req.max_tokens, temperature=req.temperature,
                scope=scope or None,
            )
        except (ProviderError, ProviderWebUIHandoff) as exc:
            logger.error(f"[Server] Vault QA failed: {exc}")
            raise HTTPException(status_code=503, detail=f"Vault QA failed: {exc}")

        if not res["answer"]:
            return HandoffResponse(status="ok", provider_used="system", actual_provider="system",
                                   timestamp=ts, reply="No relevant notes found for that question.", sources=[])

        # M30 — hallucination guard: if the answer isn't grounded in the vault, escalate
        # to a larger model and/or web-verify with real citations (private → flag only).
        from assistant_core.verify import guard_answer
        qa_private = bool(req.private) or any(self._note_is_private(s) for s in res.get("sources", []))
        answer, gstatus = guard_answer(
            res["answer"], req.message, self._router, self._config.get("vault_path"),
            self._config, private=qa_private,
        )
        if gstatus not in ("off", "grounded"):
            logger.info(f"[Server] Vault QA hallucination-guard → {gstatus}")

        if self._memory and self._ep_chat:
            self._memory.append_episode(self._ep_chat(f"[plugin vault-qa] {req.message}",
                                                      answer, provider=res["provider"]))
        return HandoffResponse(
            status="ok", reply=answer, provider_used=res["provider"],
            actual_provider=res["provider"], timestamp=ts, sources=res["sources"],
            source_kinds=res.get("source_kinds", []),
        )

    def _edit_handoff_response(self, req, original: str, private: bool, ts: str) -> "HandoffResponse":
        note = " (private — no-train providers unavailable)" if private else ""
        pkg = (
            "You are a precise text editor. Return ONLY the revised text for the region below — "
            "no preamble, no explanation, no code fences.\n\n"
            f"Instruction: {req.message}\n\nRegion to revise:\n{original}"
        )
        return HandoffResponse(
            status="edit_handoff_required",
            reply=f"No provider available for this edit{note}. Copy the prompt, paste the web AI's revised text back.",
            provider_used="webui", actual_provider="webui", timestamp=ts,
            prompt_to_copy=pkg,
        )

    def _note_project(self, note_path: str | None) -> str | None:
        """The note's `project:` frontmatter value, if any (M14 project awareness)."""
        if not note_path:
            return None
        try:
            from pathlib import Path
            from assistant_core.watcher.frontmatter_parser import FrontmatterParser
            vault = self._config.get("vault_path", "")
            if not vault:
                return None
            full = Path(vault) / note_path
            if not full.exists():
                return None
            fm, _ = FrontmatterParser.extract(full.read_text(encoding="utf-8"))
            return str(fm.get("project", "")).strip().strip('"\'') or None
        except Exception as exc:
            logger.debug(f"[Server] _note_project failed for {note_path}: {exc}")
            return None

    def _note_is_private(self, note_path: str | None) -> bool:
        """True if the target note's frontmatter is private: true (server-enforced privacy)."""
        if not note_path:
            return False
        try:
            from pathlib import Path
            from assistant_core.watcher.frontmatter_parser import FrontmatterParser
            vault = self._config.get("vault_path", "")
            if not vault:
                return False
            full = Path(vault) / note_path
            if not full.exists():
                return False
            fm, _ = FrontmatterParser.extract(full.read_text(encoding="utf-8"))
            return str(fm.get("private", "")).strip().strip('"\'').lower() in ("true", "yes", "1", "on")
        except Exception as exc:
            logger.debug(f"[Server] _note_is_private failed for {note_path}: {exc}")
            return False

    # ------------------------------------------------------------------
    # M16.5 — settings read/write + restart (the plugin's control panel)
    # ------------------------------------------------------------------

    def _admin_allowed(self) -> bool:
        """Refuse config writes/restart when the bind is public but unauthenticated —
        otherwise anyone on the LAN could rewrite settings or bounce the service."""
        public = self._host in ("0.0.0.0", "::")
        return bool(self._api_token) or not public

    def _schema_defaults(self) -> dict:
        """All known settings (from settings.example.json) so the control panel can
        show every field — including key slots and provider_sources — even when the
        live settings.json hasn't set them yet."""
        try:
            return json.loads((CONFIG_DIR / "settings.example.json").read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _redacted_settings(self) -> dict:
        merged = {**self._schema_defaults(), **self._config}   # live values win; schema fills gaps
        out = {}
        for k, v in merged.items():
            if _is_secret(k):
                out[k] = "********" if str(self._config.get(k, "")).strip() else ""
            else:
                out[k] = v
        return out

    def _apply_settings(self, payload: dict) -> dict:
        """Merge `payload` into settings.json on disk; live-apply the keys that can
        change without a restart, and report which changes need one."""
        try:
            current = json.loads(self._settings_path.read_text(encoding="utf-8"))
        except Exception:
            current = dict(self._config)

        updated: list[str] = []
        for k, v in (payload or {}).items():
            if _is_secret(k) and (not str(v).strip() or v == "********"):
                continue   # blank / unchanged placeholder → keep the existing secret
            if current.get(k) != v:
                current[k] = v
                updated.append(k)

        self._settings_path.parent.mkdir(parents=True, exist_ok=True)
        self._settings_path.write_text(json.dumps(current, indent=2, ensure_ascii=False),
                                       encoding="utf-8")

        # Live-apply the safe keys by mutating the dicts the request path reads.
        for k in updated:
            if k in LIVE_SETTING_KEYS:
                self._config[k] = current[k]
                if self._rag is not None:
                    self._rag.config[k] = current[k]

        restart_required = sorted(k for k in updated if k not in LIVE_SETTING_KEYS)
        logger.info(f"[Server] /settings updated {updated} (restart: {restart_required})")
        return {"ok": True, "updated": updated, "restart_required": restart_required}

    def _schedule_restart(self) -> None:
        def _exec():
            time.sleep(0.4)   # let the HTTP response flush first
            logger.info("[Server] Restarting (os.execv)")
            try:
                os.execv(sys.executable, [sys.executable, "-m", "assistant_core", *sys.argv[1:]])
            except Exception as exc:   # pragma: no cover
                logger.error(f"[Server] Restart failed: {exc}")
        threading.Thread(target=_exec, daemon=True, name="AssistantRestart").start()

    # ------------------------------------------------------------------
    # FastAPI app
    # ------------------------------------------------------------------

    def _build_app(self) -> "FastAPI":
        app = FastAPI(
            title       = "AI Assistant API",
            description = "Local HTTP bridge for the Obsidian plugin",
            version     = "3.0.0",
        )
        app.add_middleware(
            CORSMiddleware,
            allow_origins  = ["app://obsidian.md", "capacitor://localhost", "http://localhost"],
            allow_methods  = ["GET", "POST", "PUT"],   # PUT needed for /settings (control panel Save)
            allow_headers  = ["*"],
        )

        # ── Optional LAN auth ────────────────────────────────────────────────
        # When api_token is set (recommended whenever host is 0.0.0.0), every
        # request must carry `X-API-Key: <token>`. CORS preflight (OPTIONS) is
        # exempt so the browser/Obsidian can negotiate.
        @app.middleware("http")
        async def require_api_token(request, call_next):
            if self._api_token and request.method != "OPTIONS":
                if request.headers.get("X-API-Key", "") != self._api_token:
                    return JSONResponse({"detail": "Unauthorized — missing/invalid X-API-Key."},
                                        status_code=401)
            return await call_next(request)

        # ── GET /shutdown ────────────────────────────────────────────────────
        @app.get("/shutdown")
        async def shutdown():
            logger.info("[Server] /shutdown requested")
            if self._shutdown_event:
                self._shutdown_event.set()
            self.stop()
            return JSONResponse({"status": "shutdown_initiated",
                                 "message": "Assistant shutting down cleanly."})

        # ── GET/PUT /settings, POST /restart — the plugin control panel (M16.5) ──
        @app.get("/settings")
        async def get_settings():
            return {"settings": self._redacted_settings(),
                    "live_keys": sorted(LIVE_SETTING_KEYS),
                    "admin_allowed": self._admin_allowed()}

        @app.put("/settings")
        async def put_settings(payload: dict):
            if not self._admin_allowed():
                raise HTTPException(status_code=403,
                    detail="Admin disabled: bind is public (0.0.0.0) but no api_token is set.")
            return self._apply_settings(payload)

        @app.post("/restart")
        async def restart():
            if not self._admin_allowed():
                raise HTTPException(status_code=403,
                    detail="Admin disabled: bind is public (0.0.0.0) but no api_token is set.")
            self._schedule_restart()
            return {"status": "restarting"}

        # ── POST /chat ──────────────────────────────────────────────────────
        @app.post("/chat", response_model=HandoffResponse)
        async def chat(req: ChatRequest):
            from assistant_core.providers.base_provider import ProviderError, ProviderWebUIHandoff
            from assistant_core.agent_loop import AgentContext, run_agent_loop
            from assistant_core.memory.context_manager import ContextManager

            if not req.message.strip():
                raise HTTPException(status_code=400, detail="Message cannot be empty.")

            # M34 — the user is active: background proactive work yields for a cooldown.
            from assistant_core.background import governor
            governor.mark_foreground_activity()

            # Shutdown intercept
            if req.message.strip().lower() in ("exit", "quit", "shutdown"):
                logger.info(f"[Server] Shutdown command via /chat: {req.message!r}")
                if self._shutdown_event:
                    self._shutdown_event.set()
                self.stop()
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                return HandoffResponse(
                    status="ok", reply="Shutting down. Goodbye.",
                    provider_used="system", actual_provider="system", timestamp=ts,
                )

            # M32 — a plain arithmetic query ("4 + 6 =") is answered deterministically,
            # BEFORE any model runs, so basic math is always correct and can't be argued wrong.
            from assistant_core.tools.calc import maybe_answer_arithmetic
            _arith = maybe_answer_arithmetic(req.message)
            if _arith is not None:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                logger.info(f"[Server] Arithmetic answered deterministically: {_arith}")
                return HandoffResponse(status="ok", reply=_arith, provider_used="system",
                                       actual_provider="system", timestamp=ts)

            # Explicit `vault:` command → run the tool directly (like the terminal),
            # NOT through the agent loop. Stops the plugin sending e.g. `vault:research`
            # to the LLM, which then "kept working" instead of just returning the result.
            from assistant_core.vault_commands import VAULT_COMMANDS, handle_vault_command
            _first = req.message.strip().split(None, 1)[0].lower()

            # M19 — vault:ocr <note>: OCR the note's images into an AI/Derived sidecar.
            if _first == "vault:ocr":
                from assistant_core.media.ocr import OcrEngine, make_vision_fn
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                target = req.message.strip()[len("vault:ocr"):].strip()
                if not target:
                    return HandoffResponse(status="ok", reply="Usage: vault:ocr <note path>",
                                           provider_used="system", actual_provider="system", timestamp=ts)
                engine = OcrEngine(self._config.get("vault_path"),
                                   vision_fn=make_vision_fn(self._router, self._config))
                rep = engine.ocr_note(target, private=self._note_is_private(target))
                if rep.get("error"):
                    reply = f"OCR: {rep['error']}"
                else:
                    reply = (f"OCR: {rep['ocred']}/{rep['images']} image(s) read "
                             f"({', '.join(sorted(set(rep['engine']))) or 'none'}). "
                             f"Saved to {rep['sidecar']}.")
                    if rep["sidecar"] and self._rag and getattr(self._rag, "enabled", False):
                        try:
                            self._rag.maybe_index_note(
                                rep["sidecar"],
                                (Path(self._config["vault_path"]) / rep["sidecar"]).read_text(encoding="utf-8"))
                        except Exception:
                            pass
                if self._memory and self._ep_vault:
                    self._memory.append_episode(self._ep_vault("ocr", f"{target} → {rep.get('sidecar')}"))
                return HandoffResponse(status="ok", reply=reply, provider_used="system",
                                       actual_provider="system", timestamp=ts)

            # M18 — vault:graph <note>: extract entities/relations into AI/Graph/Entities.
            if _first == "vault:graph":
                from assistant_core.graph.job import build_graph_for_note
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                target = req.message.strip()[len("vault:graph"):].strip()
                if not target:
                    return HandoffResponse(status="ok", reply="Usage: vault:graph <note path>",
                                           provider_used="system", actual_provider="system", timestamp=ts)
                rep = build_graph_for_note(self._config.get("vault_path"), self._router, target)
                reply = (f"Graph: {rep['error']}" if rep.get("error") else
                         f"Graph: {rep['triples']} relationship(s) from {target} "
                         f"(+{rep.get('relations', 0)} new; {rep.get('entities', 0)} entities touched).")
                if self._memory and self._ep_vault:
                    self._memory.append_episode(self._ep_vault("graph", f"{target}: {rep.get('triples', 0)}"))
                return HandoffResponse(status="ok", reply=reply, provider_used="system",
                                       actual_provider="system", timestamp=ts)

            # M27 — vault:transcribe <audio>: local transcription → AI/Derived sidecar.
            if _first == "vault:transcribe":
                from assistant_core.media.audio import transcribe_to_sidecar
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                aud = req.message.strip()[len("vault:transcribe"):].strip()
                if not aud:
                    return HandoffResponse(status="ok", reply="Usage: vault:transcribe <audio path>",
                                           provider_used="system", actual_provider="system", timestamp=ts)
                rep = transcribe_to_sidecar(self._config.get("vault_path"), aud, self._config, rag=self._rag)
                reply = (f"Transcription failed: {rep['error']}." if rep.get("error") else
                         f"Transcribed ({rep['chars']} chars) → {rep['sidecar']} — now searchable.")
                if not rep.get("error") and self._memory and self._ep_vault:
                    self._memory.append_episode(self._ep_vault("transcribe", aud[:80]))
                return HandoffResponse(status="ok", reply=reply, provider_used="system",
                                       actual_provider="system", timestamp=ts)

            # M19/paperclip — vault:analyze <image>: transcribe + describe one image.
            if _first == "vault:analyze":
                from assistant_core.media.ocr import analyze_image
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                img = req.message.strip()[len("vault:analyze"):].strip()
                if not img:
                    return HandoffResponse(status="ok", reply="Usage: vault:analyze <image path>",
                                           provider_used="system", actual_provider="system", timestamp=ts)
                text, err = analyze_image(self._config.get("vault_path"), img, self._router,
                                          self._config, private=bool(req.private))
                reply = f"Image analysis failed: {err}." if err else f"**Image: {img}**\n\n{text}"
                if not err and self._memory and self._ep_vault:
                    self._memory.append_episode(self._ep_vault("analyze", img[:80]))
                return HandoffResponse(status="ok", reply=reply, provider_used="system",
                                       actual_provider="system", timestamp=ts)

            # M25 — vault:sources <claim>: which notes support this? (provenance audit)
            if _first == "vault:sources":
                from assistant_core.provenance import find_sources
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                claim = req.message.strip()[len("vault:sources"):].strip()
                if not claim:
                    return HandoffResponse(status="ok", reply="Usage: vault:sources <claim or statement>",
                                           provider_used="system", actual_provider="system", timestamp=ts)
                rep = find_sources(self._config.get("vault_path"), claim)
                if not rep["sources"]:
                    reply = "⚠ Unsourced — no notes contain these terms."
                else:
                    tag = "" if rep["sourced"] else "⚠ Weakly sourced (no single note covers most terms).\n\n"
                    reply = tag + "Supporting notes:\n" + "\n".join(
                        f"- {s['path']} ({s['matched']}/{s['of']} terms)" for s in rep["sources"])
                return HandoffResponse(status="ok", reply=reply, provider_used="system",
                                       actual_provider="system", timestamp=ts)

            # M28 — vault:cards <note> (generate flashcards) / vault:review (due count).
            if _first == "vault:cards":
                from assistant_core.study.cards import generate_cards, add_cards
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                note = req.message.strip()[len("vault:cards"):].strip()
                if not note:
                    return HandoffResponse(status="ok", reply="Usage: vault:cards <note>",
                                           provider_used="system", actual_provider="system", timestamp=ts)
                res = self._registry.run("read_note", note) if self._registry else None
                if not res or not getattr(res, "success", False):
                    reply = f"Could not read {note}."
                else:
                    cards = generate_cards(self._router, res.output)
                    added = add_cards(self._config.get("vault_path"), cards,
                                      (getattr(res, "metadata", None) or {}).get("path", note))
                    reply = f"Added {added} review card(s) from {note} (of {len(cards)} generated)."
                    if self._memory and self._ep_vault:
                        self._memory.append_episode(self._ep_vault("cards", f"{note}: {added}"))
                return HandoffResponse(status="ok", reply=reply, provider_used="system",
                                       actual_provider="system", timestamp=ts)

            if _first == "vault:review":
                from assistant_core.study.cards import due_cards
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                due = due_cards(self._config.get("vault_path"))
                if not due:
                    reply = "No cards due for review. 🎉"
                else:
                    reply = (f"{len(due)} card(s) due:\n\n" +
                             "\n\n".join(f"**Q:** {c['q']}\n**A:** {c['a']}  _(from {c['source']})_"
                                         for c in due[:10]))
                return HandoffResponse(status="ok", reply=reply, provider_used="system",
                                       actual_provider="system", timestamp=ts)

            # M26 — vault:query <expr>: structured/exact search (tag:/path:/fm:/"phrase"/NEAR).
            if _first == "vault:query":
                from assistant_core.query import structured_search
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                expr = req.message.strip()[len("vault:query"):].strip()
                if not expr:
                    return HandoffResponse(status="ok",
                                           reply='Usage: vault:query tag:sermon "the last hour" path:"06 - Projects"',
                                           provider_used="system", actual_provider="system", timestamp=ts)
                hits = structured_search(self._config.get("vault_path"), expr)
                reply = (f"No notes match `{expr}`." if not hits else
                         f"{len(hits)} note(s) match `{expr}`:\n" + "\n".join(f"- {h['path']}" for h in hits))
                return HandoffResponse(status="ok", reply=reply, provider_used="system",
                                       actual_provider="system", timestamp=ts)

            # M24 — vault:passage <ref>: assemble a cited overview of a Bible passage.
            if _first == "vault:passage":
                from assistant_core.scripture.passage import build_passage_guide
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ref = req.message.strip()[len("vault:passage"):].strip()
                if not ref:
                    return HandoffResponse(status="ok", reply="Usage: vault:passage <e.g. 1 John 2:18-20>",
                                           provider_used="system", actual_provider="system", timestamp=ts)
                rep = build_passage_guide(self._config.get("vault_path"), self._router, ref, rag=self._rag)
                reply = rep["error"] if rep.get("error") else (
                    f"**Passage: {rep['ref']}**\n\n{rep['guide']}"
                    + (f"\n\n*Notes: {', '.join(rep['notes'][:8])}*" if rep["notes"] else ""))
                if not rep.get("error") and self._memory and self._ep_vault:
                    self._memory.append_episode(self._ep_vault("passage", ref[:80]))
                return HandoffResponse(status="ok", reply=reply, provider_used="system",
                                       actual_provider="system", timestamp=ts)

            # M22 — vault:ingest <file>: extract a PDF/EPUB/DOCX/txt into AI/Library, indexed.
            if _first == "vault:ingest":
                from assistant_core.ingest.ingest import ingest_file
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                src = req.message.strip()[len("vault:ingest"):].strip()
                if not src:
                    return HandoffResponse(status="ok", reply="Usage: vault:ingest <path to document>",
                                           provider_used="system", actual_provider="system", timestamp=ts)
                rep = ingest_file(self._config.get("vault_path"), src, self._config,
                                  rag=self._rag, router=self._router)
                reply = (f"Ingest failed: {rep['error']}." if rep.get("error") else
                         f"Ingested {rep['format']} ({rep['pages']} page(s), {rep['chars']} chars) → "
                         f"{rep['note_path']} — now searchable in Vault QA.")
                if not rep.get("error") and self._memory and self._ep_vault:
                    self._memory.append_episode(self._ep_vault("ingest", f"{src} → {rep['note_path']}"))
                return HandoffResponse(status="ok", reply=reply, provider_used="system",
                                       actual_provider="system", timestamp=ts)

            # M18 — vault:guide <topic>: assemble a cited guide from the knowledge graph.
            if _first == "vault:guide":
                from assistant_core.graph.guide import build_guide
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                topic = req.message.strip()[len("vault:guide"):].strip()
                if not topic:
                    return HandoffResponse(status="ok", reply="Usage: vault:guide <topic>",
                                           provider_used="system", actual_provider="system", timestamp=ts)
                rep = build_guide(self._config.get("vault_path"), self._router, topic, rag=self._rag,
                                  include_private=bool(self._config.get("graph_include_private", False)))
                reply = rep["error"] if rep.get("error") else (
                    f"**Guide: {rep['entity']}**\n\n{rep['guide']}"
                    + (f"\n\n*Sources: {', '.join(rep['sources'][:8])}*" if rep["sources"] else ""))
                if self._memory and self._ep_vault:
                    self._memory.append_episode(self._ep_vault("guide", topic[:80]))
                return HandoffResponse(status="ok", reply=reply, provider_used="system",
                                       actual_provider="system", timestamp=ts)

            # M18 — vault:graph-merge <canonical> -> <alias>: merge two graph entities.
            if _first == "vault:graph-merge":
                from assistant_core.graph.store import merge_entities
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                arg = req.message.strip()[len("vault:graph-merge"):].strip()
                sep = "->" if "->" in arg else ("=>" if "=>" in arg else None)
                if not sep:
                    return HandoffResponse(status="ok",
                                           reply="Usage: vault:graph-merge <canonical> -> <alias>",
                                           provider_used="system", actual_provider="system", timestamp=ts)
                canon, alias = (p.strip() for p in arg.split(sep, 1))
                ok = merge_entities(self._config.get("vault_path"), canon, alias)
                reply = (f"Merged '{alias}' → '{canon}'." if ok else
                         "Could not merge (check both entities exist and differ).")
                return HandoffResponse(status="ok", reply=reply, provider_used="system",
                                       actual_provider="system", timestamp=ts)

            # M21 — vault:webresearch <query>: autonomous web research (search + fetch +
            # synthesise + save with citations). Blocked for private turns.
            if _first == "vault:webresearch":
                from assistant_core.web.research import run_web_research
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                q = req.message.strip()[len("vault:webresearch"):].strip()
                if not q:
                    return HandoffResponse(status="ok", reply="Usage: vault:webresearch <question>",
                                           provider_used="system", actual_provider="system", timestamp=ts)
                rep = run_web_research(q, self._router, self._config, rag=self._rag,
                                       private=bool(req.private))
                if rep.get("error"):
                    reply = f"Web research: {rep['error']}."
                else:
                    reply = (f"Web research saved to {rep['summary_path']} "
                             f"({len(rep['sources'])} source(s) fetched"
                             + (f", {len(rep['related'])} related note(s) linked" if rep['related'] else "")
                             + ").")
                if self._memory and self._ep_vault:
                    self._memory.append_episode(self._ep_vault("webresearch", q[:80]))
                return HandoffResponse(status="ok", reply=reply, provider_used="system",
                                       actual_provider="system", timestamp=ts)

            # M16.7 — manual discovery from the plugin (the scheduler also runs it weekly).
            # Writes the proposal for review; never auto-commits.
            if _first == "vault:discover-providers":
                from assistant_core.providers.discovery_job import run_discovery_proposal
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ok, msg = run_discovery_proposal(self._config.get("vault_path"), self._config)
                reply = (f"{msg}. Review AI/System/Provider-Registry-proposed.md, then run "
                         "`vault:update-providers apply` to commit." if ok
                         else f"Discovery could not run: {msg}.")
                if ok and self._memory and self._ep_vault:
                    self._memory.append_episode(self._ep_vault("discover_providers", msg))
                return HandoffResponse(status="ok", reply=reply, provider_used="system",
                                       actual_provider="system", timestamp=ts)

            # M34 — proactive agents, on demand (they also run on a schedule).
            if _first == "vault:briefing":
                from assistant_core.proactive.briefing import write_briefing
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                rel = write_briefing(self._config.get("vault_path"), self._config, self._rag, self._router)
                if self._memory and self._ep_vault:
                    self._memory.append_episode(self._ep_vault("briefing", rel))
                return HandoffResponse(status="ok", reply=f"Daily briefing written → {rel}",
                                       provider_used="system", actual_provider="system", timestamp=ts)

            if _first == "vault:organize":
                from assistant_core.proactive.organize import run_organize
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                rep = run_organize(self._config.get("vault_path"), self._config, self._rag,
                                   self._router, force=True)   # user asked for it now
                reply = (f"Auto-organize: staged tag/link proposals for {rep['notes']} note(s) → "
                         f"{rep['proposal']} (review and approve — nothing applied yet)."
                         if rep.get("proposal") else
                         f"Auto-organize: scanned {rep['scanned']} note(s); nothing new to propose.")
                if self._memory and self._ep_vault:
                    self._memory.append_episode(self._ep_vault("organize", str(rep.get('proposal'))))
                return HandoffResponse(status="ok", reply=reply, provider_used="system",
                                       actual_provider="system", timestamp=ts)

            # M40 — web clipper: save a page's readable text as a sourced, indexed note.
            if _first == "vault:clip":
                from assistant_core import clip
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                parts = req.message.split(None, 1)
                url = parts[1].strip() if len(parts) > 1 else ""
                if not url:
                    return HandoffResponse(status="ok", reply="Usage: vault:clip <url>",
                                           provider_used="system", actual_provider="system", timestamp=ts)
                if bool(req.private):
                    return HandoffResponse(status="ok", reply="Clipping is disabled in Private mode.",
                                           provider_used="system", actual_provider="system", timestamp=ts)
                r = clip.clip_url(self._config.get("vault_path"), url, self._rag)
                reply = (f"Clipped **{r['title']}** → {r['path']} ({r['chars']} chars"
                         f"{', indexed' if r['indexed'] else ''})."
                         if r["ok"] else f"Could not clip {url} (no readable content).")
                if r["ok"] and self._memory and self._ep_vault:
                    self._memory.append_episode(self._ep_vault("clip", r["path"]))
                return HandoffResponse(status="ok", reply=reply, provider_used="system",
                                       actual_provider="system", timestamp=ts)

            # M40 — typed/templated note fill (best-effort; propose-only).
            if _first == "vault:template":
                from assistant_core import templater
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                vault = self._config.get("vault_path")
                arg = req.message.split(None, 1)[1].strip() if len(req.message.split(None, 1)) > 1 else ""
                if not arg:
                    tpls = templater.list_templates(vault)
                    listing = ("Available templates: " + ", ".join(tpls)) if tpls else \
                              "No Templater/Templates plugin detected. Usage: vault:template <name> [context]"
                    return HandoffResponse(status="ok", reply=f"Usage: vault:template <name> [context]\n{listing}",
                                           provider_used="system", actual_provider="system", timestamp=ts)
                name, _, ctx = arg.partition("::")            # "Meeting :: optional context"
                rep = templater.fill_template(vault, name.strip(), ctx.strip(), self._router,
                                              private=bool(req.private))
                reply = (f"Filled template '{name.strip()}' → {rep['path']} "
                         f"({rep['filled']}/{rep['fields']} fields; propose-only, review & move)."
                         if rep["ok"] else f"Template fill failed: {rep.get('reason')}")
                if rep.get("ok") and self._memory and self._ep_vault:
                    self._memory.append_episode(self._ep_vault("template", rep["path"]))
                return HandoffResponse(status="ok", reply=reply, provider_used="system",
                                       actual_provider="system", timestamp=ts)

            # M39 — action layer: extract a note's to-dos into a tracked checklist.
            if _first == "vault:actions":
                from assistant_core import tasks
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                parts = req.message.split(None, 1)
                note = parts[1].strip() if len(parts) > 1 else (req.active_note_path or "")
                if not note:
                    return HandoffResponse(status="ok", reply="Usage: vault:actions <note> (or open a note first)",
                                           provider_used="system", actual_provider="system", timestamp=ts)
                if not note.endswith(".md"):
                    note += ".md"
                rel, n = tasks.write_actions(self._config.get("vault_path"), note, self._router)
                reply = (f"Extracted {n} action item(s) → {rel} (propose-only; tick them there)."
                         if rel else f"No action items found in {note}.")
                if self._memory and self._ep_vault:
                    self._memory.append_episode(self._ep_vault("actions", rel or note))
                return HandoffResponse(status="ok", reply=reply, provider_used="system",
                                       actual_provider="system", timestamp=ts)

            # M38 — vault analytics report (read-only "explain my vault").
            if _first == "vault:analytics":
                from assistant_core import analytics
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                embedder = getattr(self._rag, "embedder", None)
                rel = analytics.write_report(self._config.get("vault_path"), embedder)
                if self._memory and self._ep_vault:
                    self._memory.append_episode(self._ep_vault("analytics", rel))
                return HandoffResponse(status="ok", reply=f"Vault analytics report written → {rel}",
                                       provider_used="system", actual_provider="system", timestamp=ts)

            # M38 — Map-of-Content generation (propose-only).
            if _first == "vault:moc":
                from assistant_core import moc
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                topic = req.message.split(None, 1)[1].strip() if len(req.message.split(None, 1)) > 1 else ""
                if not topic:
                    return HandoffResponse(status="ok", reply="Usage: vault:moc <topic>",
                                           provider_used="system", actual_provider="system", timestamp=ts)
                rel = moc.build_moc(self._config.get("vault_path"), topic, self._rag, self._router)
                reply = (f"Map-of-Content proposed → {rel} (review and move/keep as you like)."
                         if rel else f"Nothing related to '{topic}' found to build a MOC.")
                if self._memory and self._ep_vault:
                    self._memory.append_episode(self._ep_vault("moc", rel or topic))
                return HandoffResponse(status="ok", reply=reply, provider_used="system",
                                       actual_provider="system", timestamp=ts)

            # M37 — contradiction detection (deterministic; propose-only, never auto-edits).
            if _first == "vault:contradictions":
                from assistant_core import contradiction
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                pairs = contradiction.detect(self._config.get("vault_path"))
                if self._memory and self._ep_vault:
                    self._memory.append_episode(self._ep_vault("contradictions", f"{len(pairs)} found"))
                return HandoffResponse(status="ok", reply=contradiction.render_report(pairs),
                                       provider_used="system", actual_provider="system", timestamp=ts)

            # M35 — goal engine controls.
            if _first == "vault:goals":
                from assistant_core.goals import store as gstore
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                goals = gstore.load_goals()
                if not goals:
                    reply = "No goals yet. Start one with `vault:goal <description>`."
                else:
                    reply = "**Goals:**\n" + "\n".join(
                        f"- `{g['slug']}` — {g['status']} ({gstore.progress(g)[0]}/{gstore.progress(g)[1]}) — {g['description'][:60]}"
                        for g in goals)
                return HandoffResponse(status="ok", reply=reply, provider_used="system",
                                       actual_provider="system", timestamp=ts)

            if _first == "vault:goal":
                from assistant_core.goals import store as gstore
                from assistant_core.goals.planner import plan_goal, plan_from_template, detect_template
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                arg = req.message.strip()[len("vault:goal"):].strip()
                verb = arg.split(None, 1)[0].lower() if arg else ""
                rest = arg.split(None, 1)[1].strip() if len(arg.split(None, 1)) > 1 else ""
                if verb in ("approve", "resume"):
                    g = gstore.set_status(rest, "running")
                    reply = (f"Goal `{rest}` is now **running** — it will progress in the background."
                             if g else f"No goal `{rest}`.")
                elif verb in ("pause", "cancel"):
                    g = gstore.set_status(rest, "paused" if verb == "pause" else "cancelled")
                    reply = f"Goal `{rest}` {verb}d." if g else f"No goal `{rest}`."
                elif not arg:
                    reply = ("Usage: vault:goal <description>  ·  vault:goal --template "
                             "research|digest|study <arg>  ·  vault:goal approve|pause|resume|cancel <slug>\n"
                             "Flags: --recurring daily|weekly|monthly · --budget <calls/day>")
                else:
                    # M39 — parse optional flags out of the description
                    tmpl = recurring = ""
                    budget = 0
                    def _flag(name, cast=str):
                        nonlocal arg
                        m = re.search(rf"--{name}\s+(\S+)", arg)
                        if m:
                            arg = (arg[:m.start()] + arg[m.end():]).strip()
                            return cast(m.group(1))
                        return None
                    tmpl = _flag("template") or ""
                    recurring = _flag("recurring") or ""
                    budget = _flag("budget", int) or 0
                    # a bare "research X" / "digest X" / "study X" auto-selects a template
                    if not tmpl:
                        auto = detect_template(arg)
                        if auto:
                            tmpl, arg = auto, arg.split(None, 1)[1] if len(arg.split(None, 1)) > 1 else arg
                    plan = plan_from_template(tmpl, arg) if tmpl else None
                    if plan is None:
                        plan = plan_goal(arg, self._router)
                    if not plan["subtasks"]:
                        reply = "Could not plan that goal — try rephrasing."
                    else:
                        g = gstore.create_goal(arg, plan["subtasks"], plan["estimate"],
                                               recurring=recurring, budget=budget,
                                               template=plan.get("template", ""))
                        gstore.render_note(self._config.get("vault_path"), g)
                        steps = "\n".join(f"{i+1}. {s}" for i, s in enumerate(plan["subtasks"]))
                        extra = []
                        if plan.get("template"): extra.append(f"template: {plan['template']}")
                        if recurring: extra.append(f"recurring: {recurring}")
                        if budget: extra.append(f"budget: {budget}/day")
                        tag = (" · " + " · ".join(extra)) if extra else ""
                        reply = (f"**Planned goal** `{g['slug']}` — {plan['estimate']}{tag}\n\n{steps}\n\n"
                                 f"Approve to run in the background: `vault:goal approve {g['slug']}`")
                        if self._memory and self._ep_vault:
                            self._memory.append_episode(self._ep_vault("goal_planned", g["slug"]))
                return HandoffResponse(status="ok", reply=reply, provider_used="system",
                                       actual_provider="system", timestamp=ts)

            if _first in VAULT_COMMANDS and self._registry is not None:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                # M20 — vault:research is a round-trip: generate a prompt for a web AI,
                # then await the pasted response. Return handoff_required so the plugin
                # shows Copy-prompt + Submit-response (reusing the M7 paste-back path).
                if _first == "vault:research":
                    q = req.message.strip()[len("vault:research"):].strip()
                    res = self._registry.run("generate_research_prompt", q)
                    if getattr(res, "success", False):
                        if self._memory and self._ep_vault:
                            self._memory.append_episode(self._ep_vault("generate_research_prompt", q[:80]))
                        return HandoffResponse(
                            status="handoff_required", timestamp=ts,
                            reply="Research prompt ready — paste it into a web AI, then submit the response.",
                            provider_used="webui", actual_provider="webui",
                            prompt_to_copy=res.output)

                # M5/T5.10 — vault:summarise loads the note, then the assistant actually
                # summarises it. Load (deterministic, robust path resolution) + ONE
                # non-agentic call → bullet summary. No agent loop (no over-continue).
                if _first in ("vault:summarise", "vault:summarize"):
                    path_arg = req.message.strip()[len(_first):].strip()
                    res = self._registry.run("summarise_research", path_arg)
                    if not getattr(res, "success", False):
                        return HandoffResponse(status="ok", reply=res.output, provider_used="system",
                                               actual_provider="system", timestamp=ts)
                    from assistant_core.providers.base_provider import Message
                    private = self._note_is_private((getattr(res, "metadata", None) or {}).get("path"))
                    reply, prov = res.output, "system"
                    if self._router and self._router.available_providers:
                        try:
                            reply, prov = self._router.generate(
                                messages=[Message(role="user", content=res.output)],
                                system_prompt=("Summarise the research note above as concise bullet "
                                               "points under Key Facts, Practical Applications, and "
                                               "Project Implications. Output only the summary."),
                                max_tokens=600, temperature=0.3, private=private,
                                allow_webui_on_private=False)
                        except Exception as exc:
                            logger.warning(f"[Server] summarise call failed ({exc}); returning loaded note")
                    if self._memory and self._ep_vault:
                        self._memory.append_episode(self._ep_vault("summarise_research", path_arg[:80]))
                    return HandoffResponse(status="ok", reply=reply, provider_used=prov,
                                           actual_provider=prov, timestamp=ts)

                out = handle_vault_command(req.message.strip(), self._registry,
                                           self._history, self._memory, logger)
                return HandoffResponse(status="ok", reply=out or "(no output)",
                                       provider_used="system", actual_provider="system", timestamp=ts)

            # M9 — edit intent bypasses the agent loop: deterministic, single-shot,
            # no history mutation, no vault: command execution. Returns a proposal.
            if req.edit:
                return self._handle_edit(req)

            # M11 — Vault QA: answer from the whole-vault RAG index (cited sources).
            if req.vault_qa:
                return self._handle_vault_qa(req)

            logger.info(f"[Server] /chat — '{req.message[:60]}'")
            tools_used: list[str] = []

            # Context injection — active note (M8) + selected region (M9).
            # Broadest context first (whole note), then the specific selection, then the message.
            # Cap each injected note so a huge file (e.g. an Excalidraw JSON blob — ~140k
            # tokens) can't blow past every provider's limit and force a web handoff.
            def _cap(path, text, limit=12000):
                if path and str(path).lower().endswith(".excalidraw.md"):
                    return "(Excalidraw drawing — raw data omitted; its typed text is searchable via Vault QA.)"
                return text if len(text) <= limit else text[:limit] + f"\n\n… [truncated — note is {len(text)} chars]"

            context_blocks: list[str] = []
            if req.active_note_path and self._registry:
                result = self._registry.run("read_note", req.active_note_path)
                if result.success:
                    context_blocks.append(f"[Active note: {req.active_note_path}]\n\n{_cap(req.active_note_path, result.output)}")
                    logger.info(f"[Server] Active note injected: {req.active_note_path} ({len(result.output)} chars)")

            # M14 — project awareness: if the active note declares `project: <name>`,
            # inject AI/Memory/Projects/<name>.md so answers are project-grounded.
            proj = self._note_project(req.active_note_path)
            if proj and self._registry:
                pres = self._registry.run("read_note", f"AI/Memory/Projects/{proj}.md")
                if pres.success:
                    context_blocks.append(f"[Project memory: {proj}]\n\n{_cap(None, pres.output)}")
                    logger.info(f"[Server] Project memory injected: {proj}")

            if isinstance(req.selection, dict) and req.selection.get("text"):
                sel_scope = req.selection.get("scope")
                sel_label = f"[Selected text — {sel_scope}]" if sel_scope else "[Selected text]"
                sel_quoted = req.selection["text"].replace("\n", "\n> ")
                context_blocks.append(f"{sel_label}\n> {sel_quoted}")
                logger.info(
                    f"[Server] Selection injected ({len(req.selection['text'])} chars, scope={sel_scope})"
                )

            # M12 — @-mentioned notes injected by name.
            mentioned = [m for m in (req.mentions or []) if m]
            for mp in mentioned:
                if self._registry:
                    result = self._registry.run("read_note", mp)
                    if result.success:
                        context_blocks.append(f"[Mentioned note: {mp}]\n\n{_cap(mp, result.output)}")
                        logger.info(f"[Server] Mention injected: {mp}")

            effective_message = req.message
            if context_blocks:
                # Frame injected context as BACKGROUND, clearly separated from the user's
                # actual request — otherwise a model reads the open note + a terse message
                # ("test") and assumes the user pasted the note. The label tells it to
                # answer the message and use the notes only if relevant.
                joined_ctx = "\n\n---\n\n".join(context_blocks)
                effective_message = (
                    "=== BACKGROUND CONTEXT (the notes the user currently has open) ===\n"
                    "This is reference material ONLY. Do NOT quote, echo, summarize, or describe "
                    "it unless the user's message below explicitly asks you to. The user did NOT "
                    "paste this and is not necessarily asking about it.\n\n"
                    f"{joined_ctx}\n\n"
                    "=== USER MESSAGE (respond to THIS and only this) ===\n"
                    "If the message is unclear, trivial, or a greeting, reply briefly and ask what "
                    "they'd like to do — do NOT dump the background.\n\n"
                    f"{req.message}"
                )

            # Privacy: any injected private source (active note or a mention) forces
            # no-train routing so its content can't leak to a training provider.
            effective_private = (
                bool(req.private)
                or self._note_is_private(req.active_note_path)
                or any(self._note_is_private(m) for m in mentioned)
            )

            try:
                ctx_mgr_inst = ContextManager(self._router.registry, router=self._router,
                                              config=self._config)
                if self._router.available_providers:
                    with self._history_lock:
                        self._history[:] = ctx_mgr_inst.trim(
                            self._history,
                            self._router.available_providers[0],
                            self._system_prompt,
                            req.max_tokens,
                            private=effective_private,
                        )

                ctx = AgentContext(
                    user_input        = effective_message,
                    history           = self._history,
                    history_lock      = self._history_lock,
                    router            = self._router,
                    registry          = self._registry,
                    memory            = self._memory,
                    ctx_mgr           = None,
                    system_prompt     = self._system_prompt,
                    max_tokens        = req.max_tokens,
                    temperature       = req.temperature,
                    provider_override = req.provider_override,
                    ep_vault_fn       = self._ep_vault,
                    ep_error_fn       = self._ep_error,
                    tools_used        = tools_used,
                    source_label      = "plugin",
                    config            = self._config,
                    rag               = self._rag,
                    private                = effective_private,
                    allow_webui_on_private = req.allow_webui_on_private,
                    max_steps              = self._config.get("max_agent_steps", 10),
                )

                reply, used_provider = run_agent_loop(ctx)

            except ProviderWebUIHandoff as handoff:
                with self._history_lock:
                    if self._history and self._history[-1].role == "user":
                        self._history.pop()
                if self._memory and self._ep_handoff:
                    self._memory.append_episode(
                        self._ep_handoff("sent", f"[plugin] {req.message[:60]}")
                    )
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                return HandoffResponse(
                    status="handoff_required",
                    reply="Web handoff required — copy the prompt below.",
                    provider_used="webui", actual_provider="webui", timestamp=ts,
                    prompt_to_copy=handoff.packaged_prompt,
                )

            except ProviderError as exc:
                with self._history_lock:
                    if self._history and self._history[-1].role == "user":
                        self._history.pop()
                err = str(exc)
                logger.error(f"[Server] Provider error: {err}")
                if self._memory and self._ep_error:
                    self._memory.append_episode(self._ep_error(f"[HTTP] {err[:120]}"))
                # Private request that exhausted all trains_on_data=no providers:
                # offer the WebUI handoff as an explicit choice rather than blocking.
                if req.private and not req.allow_webui_on_private:
                    raise HTTPException(
                        status_code=503,
                        detail=("All privacy-safe providers failed for this private request. "
                                "Resubmit with allow_webui_on_private=true to permit a WebUI "
                                "handoff (this would expose the content to a web AI)."),
                    )
                raise HTTPException(status_code=503, detail=f"Provider error: {err}")

            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # M29 — the agent staged a vault restructuring (copy/move/trash/mkdir): return
            # it as a proposal the plugin renders with Approve/Reject. Approving re-sends the
            # exact `vault:` command, which executes directly (line ~776).
            if getattr(ctx, "pending_restructure", None):
                if self._memory and self._ep_vault:
                    self._memory.append_episode(
                        self._ep_vault("propose_restructure", ctx.pending_restructure["command"][:100]))
                return HandoffResponse(
                    status="ok", reply=reply, provider_used=used_provider,
                    actual_provider=used_provider, timestamp=ts,
                    proposal=ctx.pending_restructure)

            # If the assistant produced a research prompt via the agent loop (e.g. the user
            # asked in plain language rather than typing vault:research), surface it through
            # the SAME paste-back handoff UI — a proper copy box + Submit-response — with the
            # full prompt (Question included), instead of a plain chat reply.
            if "vault:research" in tools_used and reply.strip():
                if self._memory and self._ep_vault:
                    self._memory.append_episode(self._ep_vault("generate_research_prompt", req.message[:80]))
                return HandoffResponse(
                    status="handoff_required", timestamp=ts,
                    reply="Research prompt ready — paste it into a web AI, then submit the response.",
                    provider_used="webui", actual_provider="webui", prompt_to_copy=reply)

            if self._memory and self._ep_chat:
                self._memory.append_episode(
                    self._ep_chat(f"[plugin] {req.message}", reply, provider=used_provider)
                )

            return HandoffResponse(
                status="ok", reply=reply,
                provider_used=used_provider, actual_provider=used_provider, timestamp=ts,
            )

        # ── POST /chat/handoff-return ───────────────────────────────────────
        @app.post("/chat/handoff-return", response_model=HandoffResponse)
        async def handoff_return(req: HandoffReturnRequest):
            """
            Process a web AI response pasted back by the user.

            New behaviour: scan the response for plain-English vault search
            suggestions. Convert them to vault commands and execute them via
            the registry. Append results to the response before storing.

            This makes the handoff a research loop — the web AI says
            "you may want to search for X", the system does it automatically,
            and the enriched result is ready to send back to the web AI.
            """
            from assistant_core.providers.base_provider import Message

            if not req.response_text.strip():
                raise HTTPException(status_code=400, detail="response_text cannot be empty.")

            logger.info(f"[Server] /chat/handoff-return — {len(req.response_text)} chars")

            response_text    = req.response_text
            vault_actions    = []

            # Check for plain-English vault suggestions and execute them
            if self._registry:
                suggestions = extract_vault_suggestions(req.response_text)
                if suggestions:
                    logger.info(f"[Server] Found {len(suggestions)} vault suggestion(s) in handoff return")
                    results_block = "\n\n---\n**Vault search results (executed automatically):**\n\n"
                    for cmd in suggestions:
                        parts     = cmd.split(None, 1)
                        tool_name_map = {
                            "vault:search": "search_vault",
                            "vault:read":   "read_note",
                            "vault:list":   "list_vault",
                        }
                        tool_name = tool_name_map.get(parts[0].lower())
                        if tool_name and len(parts) > 1:
                            result = self._registry.run(tool_name, parts[1].strip())
                            status = "✓" if result.success else "✗"
                            results_block += f"**{cmd}** {status}\n\n{result.output}\n\n"
                            vault_actions.append(cmd)
                            logger.info(f"[Server] Executed vault suggestion: {cmd}")
                            if self._ep_vault and self._memory:
                                self._memory.append_episode(
                                    self._ep_vault(parts[0], parts[1] + " [handoff-suggestion]")
                                )

                    response_text = response_text + results_block

            original = req.original_message or "[web handoff — original question not recorded]"

            # M20 (hardened, T5.01) — save VERBATIM, then summarise with ONE non-agentic
            # call and append related notes DETERMINISTICALLY from the index. The model
            # never searches or writes links, so it can't invent note paths or loop.
            from assistant_core.research_roundtrip import (
                save_research_verbatim, summarize_research, append_related_notes,
            )
            saved_path = save_research_verbatim(self._registry, req.response_text)
            if saved_path:
                vault_actions.append(f"vault:import → {saved_path}")
                logger.info(f"[Server] Research saved verbatim: {saved_path}")

            summary = summarize_research(self._router, original, req.response_text, private=False)
            related = append_related_notes(self._rag, self._config.get("vault_path"), saved_path)
            synthesised = bool(summary)

            reply = summary or (f"Research saved to {saved_path}." if saved_path else response_text)
            if saved_path:
                reply += f"\n\n*Saved to {saved_path}.*"
            if related:
                reply += f"\n*Linked {len(related)} related note(s) from your vault.*"
                vault_actions.append(f"related → {len(related)}")
            with self._history_lock:
                self._history.append(Message(role="assistant", content=reply))

            # Episode logging — both the handoff marker and the chat entry
            if self._memory and self._ep_handoff:
                self._memory.append_episode(
                    self._ep_handoff("returned", f"{len(req.response_text)} chars from plugin"
                                     + (" + summarised" if synthesised else ""))
                )
            if self._memory and self._ep_chat:
                self._memory.append_episode(
                    self._ep_chat(f"[plugin] {original}", reply, provider="web")
                )

            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return HandoffResponse(
                status="ok", reply=reply,
                provider_used="webui", actual_provider="webui", timestamp=ts,
                vault_actions_taken=vault_actions,
            )

        # ── M18 — knowledge-graph subgraph for the plugin viewer ────────────
        @app.get("/graph")
        async def graph(node: str, depth: int = 1):
            """Local subgraph (entity + neighbours to `depth`) from AI/Graph/Entities."""
            from assistant_core.graph.store import read_subgraph
            vault = self._config.get("vault_path")
            if not vault:
                return {"nodes": [], "edges": []}
            return read_subgraph(vault, node, depth=max(1, min(int(depth), 3)),
                                 include_private=bool(self._config.get("graph_include_private", False)))

        @app.get("/graph/entities")
        async def graph_entities(limit: int = 100):
            """All graph entities (most-connected first) so the viewer can offer nodes."""
            from assistant_core.graph.store import list_entities
            vault = self._config.get("vault_path")
            if not vault:
                return {"entities": []}
            ents = list_entities(vault, include_private=bool(self._config.get("graph_include_private", False)))
            return {"entities": ents[:max(1, min(int(limit), 500))]}

        # ── M17 Slice 4 — Memory review (consolidation proposals) ───────────
        @app.get("/memory/proposals")
        async def memory_proposals():
            """Pending nightly-consolidation proposals for the plugin's review panel."""
            from assistant_core.consolidation import list_proposals
            vault = self._config.get("vault_path")
            return {"proposals": list_proposals(vault) if vault else []}

        @app.post("/memory/proposals/apply")
        async def memory_proposals_apply(req: MemoryApplyRequest):
            """Merge accepted facts into Learned-Facts and resolve the proposal."""
            from assistant_core.consolidation import apply_proposal
            vault = self._config.get("vault_path")
            if not vault:
                raise HTTPException(status_code=400, detail="No vault configured.")
            result = apply_proposal(vault, req.filename, req.accepted)
            if self._memory and self._ep_vault:
                self._memory.append_episode(
                    self._ep_vault("consolidate_apply",
                                   f"{result['applied']} fact(s) from {req.filename}"))
            return result

        # ── M34 proactive agents (briefing + auto-organize proposals) ────────
        @app.get("/proactive")
        async def proactive_state():
            from assistant_core.proactive.organize import load_pending
            vault = self._config.get("vault_path")
            date = datetime.now().strftime("%Y-%m-%d")
            bpath = f"AI/Briefings/{date}.md"
            bexists = bool(vault) and (Path(vault) / bpath).exists()
            return {"briefing": {"path": bpath, "exists": bexists}, "proposals": load_pending()}

        @app.post("/proactive/apply")
        async def proactive_apply(payload: dict):
            from assistant_core.proactive.organize import apply_suggestion, apply_one, load_pending
            payload = payload or {}
            vault = self._config.get("vault_path")
            note = payload.get("note")
            if not vault or not note:
                raise HTTPException(status_code=400, detail="note required")
            tag, link = payload.get("tag"), payload.get("link")
            if tag or link:                      # M35.1 — apply just one tag or link
                kind, value = ("tag", tag) if tag else ("link", link)
                ok = apply_one(vault, note, kind, value)
                if ok and self._memory and self._ep_vault:
                    self._memory.append_episode(self._ep_vault("organize_apply", f"{note} · {kind}:{value}"))
                return {"applied": ok, "note": note, "kind": kind, "value": value}
            sugg = next((s for s in load_pending() if s.get("note") == note), None)
            if sugg is None:
                return {"applied": False, "reason": "not found"}
            ok = apply_suggestion(vault, note, sugg.get("tags"), sugg.get("related"))
            if ok and self._memory and self._ep_vault:
                self._memory.append_episode(self._ep_vault("organize_apply", note))
            return {"applied": ok, "note": note}

        @app.post("/proactive/reject")
        async def proactive_reject(payload: dict):
            from assistant_core.proactive.organize import reject_one, reject_all
            payload = payload or {}
            note = payload.get("note")
            if not note:
                raise HTTPException(status_code=400, detail="note required")
            tag, link = payload.get("tag"), payload.get("link")
            if tag or link:                      # M35.1 — dismiss just one tag or link
                kind, value = ("tag", tag) if tag else ("link", link)
                reject_one(note, kind, value)
                return {"rejected": True, "note": note, "kind": kind, "value": value}
            reject_all(note)
            return {"rejected": True, "note": note}

        @app.post("/proactive/run")
        async def proactive_run(payload: dict):
            agent = (payload or {}).get("agent", "")
            vault = self._config.get("vault_path")
            if agent == "briefing":
                from assistant_core.proactive.briefing import write_briefing
                return {"ran": "briefing", "path": write_briefing(vault, self._config, self._rag, self._router)}
            if agent == "organize":
                from assistant_core.proactive.organize import run_organize
                rep = run_organize(vault, self._config, self._rag, self._router, force=True)
                return {"ran": "organize", **rep}
            raise HTTPException(status_code=400, detail="agent must be 'briefing' or 'organize'")

        # ── M36 unified Approvals inbox (organize + memory + goals) ──────────
        @app.get("/approvals")
        async def approvals_list():
            from assistant_core.approvals import list_approvals
            return {"approvals": list_approvals(self._config.get("vault_path"))}

        @app.post("/approvals/apply")
        async def approvals_apply(payload: dict):
            from assistant_core.approvals import apply_approval
            payload = payload or {}
            aid = payload.get("id")
            if not aid:
                raise HTTPException(status_code=400, detail="id required")
            res = apply_approval(self._config.get("vault_path"), aid, payload.get("item"))
            if res.get("applied") and self._memory and self._ep_vault:
                self._memory.append_episode(self._ep_vault("approval_apply", aid))
            return {"id": aid, **res}

        @app.post("/approvals/reject")
        async def approvals_reject(payload: dict):
            from assistant_core.approvals import reject_approval
            payload = payload or {}
            aid = payload.get("id")
            if not aid:
                raise HTTPException(status_code=400, detail="id required")
            return {"id": aid, **reject_approval(self._config.get("vault_path"), aid, payload.get("item"))}

        # ── M39 goals panel: list + running-goal controls (approval is in /approvals) ──
        @app.get("/goals")
        async def goals_list():
            from assistant_core.goals import store as gs
            out = []
            for g in gs.load_goals():
                done, total = gs.progress(g)
                out.append({"slug": g["slug"], "description": g["description"],
                            "status": g["status"], "done": done, "total": total,
                            "recurring": g.get("recurring", ""), "template": g.get("template", "")})
            return {"goals": out}

        @app.post("/goals/control")
        async def goals_control(payload: dict):
            from assistant_core.goals import store as gs
            payload = payload or {}
            slug, action = payload.get("slug"), payload.get("action")
            status_map = {"resume": "running", "pause": "paused", "cancel": "cancelled"}
            if not slug or action not in status_map:
                raise HTTPException(status_code=400, detail="slug + action(resume|pause|cancel) required")
            g = gs.set_status(slug, status_map[action])
            return {"ok": bool(g), "slug": slug, "status": status_map[action]}

        # ── GET /status ─────────────────────────────────────────────────────
        @app.get("/status", response_model=StatusResponse)
        async def status():
            avail = self._router.available_providers
            return StatusResponse(
                online=True,
                providers=self._router.status(),
                active_provider=avail[0] if avail else None,
                provider_override=self._provider_override,
                session_started=self._session_start,
                message_count=len(self._history),
            )

        # ── GET /relevant ────────────────────────────────────────────────────
        @app.get("/relevant")
        async def relevant(path: str, k: int = 5):
            """M12 — notes semantically related to `path` (from the Vault QA index)."""
            if not self._rag or not self._rag.has_index():
                return {"notes": []}
            try:
                return {"notes": self._rag.relevant_notes(path, k=k)}
            except Exception as exc:
                logger.warning(f"[Server] /relevant failed for {path}: {exc}")
                return {"notes": []}

        # ── GET /history ────────────────────────────────────────────────────
        @app.get("/history", response_model=HistoryResponse)
        async def history():
            with self._history_lock:
                snapshot = list(self._history)

            skip_prefixes = (
                "[Vault context loaded by tool",
                "[Earlier vault load",
                "[Vault load by",
                "[Older message trimmed",
                "[Tool execution complete",
                "[Tool result for",
                "[SYSTEM HINT]",
                "[Blocked:",
                "[Active note:",
                "[Mentioned note:",
                "[Selected text",
            )
            skip_exact = {
                "[Trimmed]",
                "Vault content loaded. Ready to help.",
            }

            visible = [
                HistoryMessage(role=m.role, content=m.content)
                for m in snapshot
                if not any(m.content.startswith(p) for p in skip_prefixes)
                and m.content not in skip_exact
            ]
            return HistoryResponse(messages=visible, count=len(visible))

        return app
