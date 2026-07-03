"""Pydantic request/response models for the HTTP API.

`_fastapi_available` reflects the whole server stack (uvicorn + fastapi +
pydantic). When it's False the models are simply undefined — the server runs as
a no-op and never references them.
"""

_fastapi_available = False
try:
    import uvicorn  # noqa: F401
    from fastapi import FastAPI, HTTPException  # noqa: F401
    from fastapi.middleware.cors import CORSMiddleware  # noqa: F401
    from fastapi.responses import JSONResponse  # noqa: F401
    from pydantic import BaseModel
    _fastapi_available = True
except ImportError:
    pass


if _fastapi_available:
    class ChatRequest(BaseModel):
        message:           str
        max_tokens:        int   = 2048
        temperature:       float = 0.7
        provider_override: str | None = None
        active_note_path:  str | None = None   # M8 active note context
        private:                 bool = False  # M10 — privacy-only routing
        allow_webui_on_private:  bool = False  # M10 — opt-in to WebUI handoff for private
        # M9 — selected-region context. The plugin owns the offsets; the server only
        # reads text + scope for context injection (offsets pass through opaquely).
        selection:         dict | None = None  # { text, from, to, scope }
        scope:             str | None  = None  # word | paragraph | section | whole-note
        edit:              bool = False        # M9 — propose an edit instead of a chat reply
        vault_qa:          bool = False        # M11 — answer from the whole-vault RAG index
        mentions:          list[str] = []      # M12 — extra notes (paths) to inject as context
        scope_folder:      str | None = None   # M12 — restrict Vault QA to a folder prefix
        scope_tag:         str | None = None   # M12 — restrict Vault QA to a tag

    class HandoffResponse(BaseModel):
        status:              str
        reply:               str
        provider_used:       str
        actual_provider:     str
        timestamp:           str
        prompt_to_copy:      str | None = None
        vault_actions_taken: list[str]  = []   # commands executed on handoff return
        proposal:            dict | None = None  # M9 — EditProposal when status=ok and edit was requested
        sources:             list[str]  = []   # M11 — Vault QA source notes (path#heading)
        source_kinds:        list[str]  = []   # M16 — "vector"|"graph" per source (aligned with sources)

    class HandoffReturnRequest(BaseModel):
        response_text:    str
        original_message: str | None = None

    class MemoryApplyRequest(BaseModel):        # M17 Slice 4 — Memory review panel
        filename: str
        accepted: list[str] = []

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
