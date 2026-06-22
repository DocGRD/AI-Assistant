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

import logging
import re
import threading
from datetime import datetime

logger = logging.getLogger("assistant")

_fastapi_available = False
try:
    import uvicorn
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel
    _fastapi_available = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Vault suggestion patterns — plain English phrases a web AI might use
# when it wants a vault search but can't issue commands
# ---------------------------------------------------------------------------

_VAULT_SUGGESTION_PATTERNS = [
    # "search your vault for X" → vault:search X
    (re.compile(
        r"search(?:\s+your)?\s+vault\s+for\s+[\"']?([^\"'\n\.]{3,60})[\"']?",
        re.IGNORECASE),
     "vault:search {0}"),
    # "check your notes on X" → vault:search X
    (re.compile(
        r"check(?:\s+your)?\s+(?:notes?|vault)\s+(?:on|about|for)\s+[\"']?([^\"'\n\.]{3,60})[\"']?",
        re.IGNORECASE),
     "vault:search {0}"),
    # "look in your vault for X" → vault:search X
    (re.compile(
        r"look(?:\s+in)?\s+(?:your\s+)?(?:vault|notes?)\s+(?:for|about)\s+[\"']?([^\"'\n\.]{3,60})[\"']?",
        re.IGNORECASE),
     "vault:search {0}"),
]

def _extract_vault_suggestions(text: str) -> list[str]:
    """
    Convert plain-English vault search suggestions from a web AI response
    into actual vault: commands the agent loop can execute.
    """
    commands = []
    for pattern, template in _VAULT_SUGGESTION_PATTERNS:
        for match in pattern.finditer(text):
            query   = match.group(1).strip().rstrip(".")
            command = template.format(query)
            if command not in commands:
                commands.append(command)
    return commands


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

if _fastapi_available:
    class ChatRequest(BaseModel):
        message:           str
        max_tokens:        int   = 2048
        temperature:       float = 0.7
        provider_override: str | None = None
        active_note_path:  str | None = None   # M8 active note context

    class HandoffResponse(BaseModel):
        status:              str
        reply:               str
        provider_used:       str
        actual_provider:     str
        timestamp:           str
        prompt_to_copy:      str | None = None
        vault_actions_taken: list[str]  = []   # commands executed on handoff return

    class HandoffReturnRequest(BaseModel):
        response_text:    str
        original_message: str | None = None

    class HistoryMessage(BaseModel):
        role:    str
        content: str

    class StatusResponse(BaseModel):
        online:            bool
        providers:         dict[str, bool]
        active_provider:   str | None
        provider_override: str | None
        session_started:   str
        message_count:     int

    class HistoryResponse(BaseModel):
        messages: list[HistoryMessage]
        count:    int


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
    ):
        self._router         = router
        self._memory         = memory
        self._registry       = registry
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
        print(f"[HTTP API active on http://{self._host}:{self._port}]\n")

    def stop(self) -> None:
        if self._server:
            self._server.should_exit = True
            logger.info("[Server] HTTP server stopping")

    def is_available(self) -> bool:
        return _fastapi_available

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
            allow_methods  = ["GET", "POST"],
            allow_headers  = ["*"],
        )

        # ── GET /shutdown ────────────────────────────────────────────────────
        @app.get("/shutdown")
        async def shutdown():
            logger.info("[Server] /shutdown requested")
            if self._shutdown_event:
                self._shutdown_event.set()
            self.stop()
            return JSONResponse({"status": "shutdown_initiated",
                                 "message": "Assistant shutting down cleanly."})

        # ── POST /chat ──────────────────────────────────────────────────────
        @app.post("/chat", response_model=HandoffResponse)
        async def chat(req: ChatRequest):
            from providers.base_provider import ProviderError, ProviderWebUIHandoff
            from agent_loop import AgentContext, run_agent_loop
            from memory.context_manager import ContextManager

            if not req.message.strip():
                raise HTTPException(status_code=400, detail="Message cannot be empty.")

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

            logger.info(f"[Server] /chat — '{req.message[:60]}'")
            tools_used: list[str] = []

            # Active note injection (M8)
            effective_message = req.message
            if req.active_note_path and self._registry:
                result = self._registry.run("read_note", req.active_note_path)
                if result.success:
                    effective_message = (
                        f"[Active note: {req.active_note_path}]\n\n"
                        f"{result.output}\n\n---\n\n{req.message}"
                    )
                    logger.info(f"[Server] Active note injected: {req.active_note_path}")

            try:
                ctx_mgr_inst = ContextManager(self._router.registry)
                if self._router.available_providers:
                    with self._history_lock:
                        self._history[:] = ctx_mgr_inst.trim(
                            self._history,
                            self._router.available_providers[0],
                            self._system_prompt,
                            req.max_tokens,
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
                raise HTTPException(status_code=503, detail=f"Provider error: {err}")

            if self._memory and self._ep_chat:
                self._memory.append_episode(
                    self._ep_chat(f"[plugin] {req.message}", reply, provider=used_provider)
                )

            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
            from providers.base_provider import Message

            if not req.response_text.strip():
                raise HTTPException(status_code=400, detail="response_text cannot be empty.")

            logger.info(f"[Server] /chat/handoff-return — {len(req.response_text)} chars")

            response_text    = req.response_text
            vault_actions    = []

            # Check for plain-English vault suggestions and execute them
            if self._registry:
                suggestions = _extract_vault_suggestions(req.response_text)
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

            # Store the enriched response in history
            with self._history_lock:
                self._history.append(Message(role="assistant", content=response_text))

            # Episode logging — both the handoff marker and the chat entry
            if self._memory and self._ep_handoff:
                self._memory.append_episode(
                    self._ep_handoff("returned", f"{len(req.response_text)} chars from plugin")
                )
            if self._memory and self._ep_chat:
                original = req.original_message or "[web handoff — original question not recorded]"
                self._memory.append_episode(
                    self._ep_chat(f"[plugin] {original}", response_text, provider="web")
                )

            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return HandoffResponse(
                status="ok", reply=response_text,
                provider_used="webui", actual_provider="webui", timestamp=ts,
                vault_actions_taken=vault_actions,
            )

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
