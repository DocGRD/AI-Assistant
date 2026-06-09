"""
HTTP Server — Milestone 6
=========================
Exposes the assistant's chat loop to the Obsidian plugin via a local HTTP API.
Runs as a daemon thread alongside the chat loop and vault watcher.

Endpoints:
    POST /chat        — Send a message, get a reply
    GET  /status      — Provider health, current session state
    GET  /history     — Current session conversation history

The server shares the same router, memory, registry, and history list as the
terminal chat loop — it is not a separate assistant, it IS the assistant,
accessed through a different interface.

Usage (from assistant.py):
    from server import AssistantServer
    server = AssistantServer(router, memory, registry, history, config)
    server.start()   # starts uvicorn in a daemon thread
    ...
    server.stop()    # signals shutdown
"""

import logging
import threading
from datetime import datetime
from typing import Any

logger = logging.getLogger("assistant")

# These are imported lazily so the rest of the app works if fastapi isn't installed
_fastapi_available = False
try:
    import uvicorn
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel
    _fastapi_available = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

if _fastapi_available:
    class ChatRequest(BaseModel):
        message: str
        max_tokens: int = 2048
        temperature: float = 0.7

    class ChatResponse(BaseModel):
        reply: str
        provider_used: str
        timestamp: str

    class HistoryMessage(BaseModel):
        role: str
        content: str

    class StatusResponse(BaseModel):
        online: bool
        providers: dict[str, bool]
        active_provider: str | None
        session_started: str
        message_count: int

    class HistoryResponse(BaseModel):
        messages: list[HistoryMessage]
        count: int


# ---------------------------------------------------------------------------
# Server class
# ---------------------------------------------------------------------------

class AssistantServer:
    """
    Wraps a FastAPI app and runs it in a background daemon thread.
    Holds references to the live assistant objects so all threads share state.
    """

    def __init__(
        self,
        router,           # ProviderRouter
        memory,           # MemoryManager | None
        registry,         # ToolRegistry | None
        history: list,    # the shared conversation history list
        config: dict,
        system_prompt: str = "",
        ep_chat_fn=None,  # ep_chat() formatter from assistant.py
        ep_error_fn=None, # ep_error() formatter from assistant.py
    ):
        self._router        = router
        self._memory        = memory
        self._registry      = registry
        self._history       = history
        self._config        = config
        self._system_prompt = system_prompt
        self._ep_chat       = ep_chat_fn
        self._ep_error      = ep_error_fn
        self._host          = config.get("host", "127.0.0.1")
        self._port          = config.get("port", 8765)
        self._session_start = datetime.now().strftime("%Y-%m-%d %H:%M")
        self._thread: threading.Thread | None = None
        self._server: uvicorn.Server | None = None
        self._last_provider_used: str = "none"

        if not _fastapi_available:
            logger.warning("[Server] FastAPI/uvicorn not installed — HTTP server disabled.")
            logger.warning("[Server] Run: pip install fastapi uvicorn")
            return

        self._app = self._build_app()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the HTTP server in a background daemon thread."""
        if not _fastapi_available:
            print("[HTTP server disabled — run: pip install fastapi uvicorn]\n")
            return

        cfg = uvicorn.Config(
            app          = self._app,
            host         = self._host,
            port         = self._port,
            log_level    = "warning",  # keep uvicorn quiet; our logger handles it
            loop         = "asyncio",
            access_log   = False,
        )
        self._server = uvicorn.Server(cfg)

        self._thread = threading.Thread(
            target  = self._server.run,
            daemon  = True,
            name    = "AssistantHTTPServer",
        )
        self._thread.start()
        logger.info(f"[Server] HTTP server started on http://{self._host}:{self._port}")
        print(f"[HTTP API active on http://{self._host}:{self._port}]\n")

    def stop(self) -> None:
        """Signal the server to shut down."""
        if self._server:
            self._server.should_exit = True
            logger.info("[Server] HTTP server stopping...")

    def is_available(self) -> bool:
        return _fastapi_available

    # ------------------------------------------------------------------
    # FastAPI app builder
    # ------------------------------------------------------------------

    def _build_app(self) -> "FastAPI":
        app = FastAPI(
            title       = "AI Assistant API",
            description = "Local HTTP bridge for the Obsidian plugin",
            version     = "1.0.0",
        )

        # Allow the Obsidian plugin (running in a webview) to call us
        app.add_middleware(
            CORSMiddleware,
            allow_origins  = ["app://obsidian.md", "capacitor://localhost", "http://localhost"],
            allow_methods  = ["GET", "POST"],
            allow_headers  = ["*"],
        )

        # ── POST /chat ─────────────────────────────────────────────────────
        @app.post("/chat", response_model=ChatResponse)
        async def chat(req: ChatRequest):
            """Send a message and receive a reply from the active AI provider."""
            from providers.base_provider import Message, ProviderError
            from providers.model_registry import estimate_tokens
            from memory.context_manager import ContextManager

            if not req.message.strip():
                raise HTTPException(status_code=400, detail="Message cannot be empty.")

            logger.info(f"[Server] /chat — '{req.message[:60]}'")

            # Trim context before adding the new message (same logic as terminal loop)
            ctx_mgr = ContextManager(self._router.registry)
            if self._router.available_providers:
                trimmed = ctx_mgr.trim(
                    self._history,
                    self._router.available_providers[0],
                    self._system_prompt,
                    req.max_tokens,
                )
                # Replace contents in-place so the terminal loop sees the same list
                self._history[:] = trimmed

            self._history.append(Message(role="user", content=req.message))

            try:
                reply = self._router.generate(
                    messages      = self._history,
                    system_prompt = self._system_prompt,
                    max_tokens    = req.max_tokens,
                    temperature   = req.temperature,
                )
            except ProviderError as exc:
                # Remove the user message we just added so history stays clean
                self._history.pop()
                err = str(exc)
                logger.error(f"[Server] Provider error: {err}")
                if self._memory and self._ep_error:
                    self._memory.append_episode(self._ep_error(f"[HTTP] {err[:120]}"))
                raise HTTPException(status_code=503, detail=f"Provider error: {err}")

            self._history.append(Message(role="assistant", content=reply))
            self._last_provider_used = (
                self._router.available_providers[0]
                if self._router.available_providers else "unknown"
            )

            # Write to episode log — same as terminal loop
            if self._memory and self._ep_chat:
                self._memory.append_episode(
                    self._ep_chat(f"[plugin] {req.message}", reply)
                )

            logger.info(f"[Server] Reply sent ({len(reply)} chars)")
            return ChatResponse(
                reply            = reply,
                provider_used    = self._last_provider_used,
                timestamp        = datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )

        # ── GET /status ────────────────────────────────────────────────────
        @app.get("/status", response_model=StatusResponse)
        async def status():
            """Return provider health and session metadata."""
            avail = self._router.available_providers
            return StatusResponse(
                online          = True,
                providers       = self._router.status(),
                active_provider = avail[0] if avail else None,
                session_started = self._session_start,
                message_count   = len(self._history),
            )

        # ── GET /history ───────────────────────────────────────────────────
        @app.get("/history", response_model=HistoryResponse)
        async def history():
            """Return the current session's conversation history."""
            # Filter out vault context injections — they're noisy in the UI
            visible = [
                HistoryMessage(role=m.role, content=m.content)
                for m in self._history
                if not m.content.startswith("[Vault context loaded by tool")
                and not m.content.startswith("[Earlier vault load")
                and not m.content.startswith("[Vault load by")
                and not m.content.startswith("[Older message trimmed")
            ]
            return HistoryResponse(messages=visible, count=len(visible))

        return app
