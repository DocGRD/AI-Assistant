"""
HTTP Server — T7.5.11 headless shutdown fix

Changes:
  - shutdown_event: threading.Event added as constructor parameter.
  - GET /shutdown endpoint: sets shutdown_event, stops the server,
    returns 200. Works from a browser, curl, or the plugin.
  - POST /chat now intercepts "exit" and "quit" as special messages
    and triggers shutdown instead of sending them to the AI.
    This handles the case where the user types exit/quit in the
    Obsidian plugin sidebar while the service is in headless mode.
"""

import logging
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
# Request / Response models
# ---------------------------------------------------------------------------

if _fastapi_available:
    class ChatRequest(BaseModel):
        message:           str
        max_tokens:        int   = 2048
        temperature:       float = 0.7
        provider_override: str | None = None
        active_note_path:  str | None = None

    class HandoffResponse(BaseModel):
        status:          str
        reply:           str
        provider_used:   str
        actual_provider: str
        timestamp:       str
        prompt_to_copy:  str | None = None

    class HandoffReturnRequest(BaseModel):
        response_text:    str
        original_message: str | None = None   # the user question that triggered the handoff

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
        system_prompt:  str            = "",
        ep_chat_fn                     = None,
        ep_error_fn                    = None,
        ep_handoff_fn                  = None,
        ep_vault_fn                    = None,
        shutdown_event: threading.Event | None = None,  # T7.5.11
    ):
        self._router          = router
        self._memory          = memory
        self._registry        = registry
        self._history         = history
        self._history_lock    = history_lock
        self._config          = config
        self._system_prompt   = system_prompt
        self._ep_chat         = ep_chat_fn
        self._ep_error        = ep_error_fn
        self._ep_handoff      = ep_handoff_fn
        self._ep_vault        = ep_vault_fn
        self._shutdown_event  = shutdown_event  # T7.5.11
        self._host            = config.get("host",  "127.0.0.1")
        self._port            = config.get("port",  8765)
        self._session_start   = datetime.now().strftime("%Y-%m-%d %H:%M")
        self._thread          = None
        self._server          = None
        self._provider_override: str | None = None

        if not _fastapi_available:
            logger.warning("[Server] FastAPI/uvicorn not installed — HTTP server disabled.")
            return

        self._app = self._build_app()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

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
    # FastAPI app builder
    # ------------------------------------------------------------------

    def _build_app(self) -> "FastAPI":
        app = FastAPI(
            title       = "AI Assistant API",
            description = "Local HTTP bridge for the Obsidian plugin",
            version     = "2.3.0",
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
            """
            T7.5.11: Trigger a clean shutdown of the assistant service.
            Sets the shared shutdown_event so run_headless() exits its
            polling loop and performs a clean episode close.
            """
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

            if not req.message.strip():
                raise HTTPException(status_code=400, detail="Message cannot be empty.")

            # T7.5.11: intercept exit/quit as shutdown commands
            if req.message.strip().lower() in ("exit", "quit", "shutdown"):
                logger.info(f"[Server] Shutdown command received via /chat: {req.message!r}")
                if self._shutdown_event:
                    self._shutdown_event.set()
                self.stop()
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                return HandoffResponse(
                    status          = "ok",
                    reply           = "Shutting down the assistant service. Goodbye.",
                    provider_used   = "system",
                    actual_provider = "system",
                    timestamp       = ts,
                )

            logger.info(f"[Server] /chat — '{req.message[:60]}'")

            tools_used: list[str] = []

            try:
                # Trim context before agent loop
                from memory.context_manager import ContextManager
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
                    user_input        = req.message,
                    history           = self._history,
                    history_lock      = self._history_lock,
                    router            = self._router,
                    registry          = self._registry,
                    memory            = self._memory,
                    ctx_mgr           = None,   # trimmed above
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
                    status          = "handoff_required",
                    reply           = "Web handoff required — copy the prompt and paste in a web AI.",
                    provider_used   = "webui",
                    actual_provider = "webui",
                    timestamp       = ts,
                    prompt_to_copy  = handoff.packaged_prompt,
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
                status          = "ok",
                reply           = reply,
                provider_used   = used_provider,
                actual_provider = used_provider,
                timestamp       = ts,
                prompt_to_copy  = None,
            )

        # ── POST /chat/handoff-return ───────────────────────────────────────
        @app.post("/chat/handoff-return", response_model=HandoffResponse)
        async def handoff_return(req: HandoffReturnRequest):
            from providers.base_provider import Message

            if not req.response_text.strip():
                raise HTTPException(status_code=400, detail="response_text cannot be empty.")

            logger.info(f"[Server] /chat/handoff-return — {len(req.response_text)} chars")

            with self._history_lock:
                self._history.append(Message(role="assistant", content=req.response_text))

            if self._memory and self._ep_handoff:
                self._memory.append_episode(
                    self._ep_handoff("returned", f"{len(req.response_text)} chars from plugin")
                )

            # Write the full exchange to the episode log so the response
            # is actually readable in the episode file, not just the 🌐 markers.
            if self._memory and self._ep_chat:
                original = req.original_message or "[web handoff — original question not recorded]"
                self._memory.append_episode(
                    self._ep_chat(f"[plugin] {original}", req.response_text, provider="web")
                )

            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return HandoffResponse(
                status          = "ok",
                reply           = req.response_text,
                provider_used   = "webui",
                actual_provider = "webui",
                timestamp       = ts,
                prompt_to_copy  = None,
            )

        # ── GET /status ─────────────────────────────────────────────────────
        @app.get("/status", response_model=StatusResponse)
        async def status():
            avail = self._router.available_providers
            return StatusResponse(
                online            = True,
                providers         = self._router.status(),
                active_provider   = avail[0] if avail else None,
                provider_override = self._provider_override,
                session_started   = self._session_start,
                message_count     = len(self._history),
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
