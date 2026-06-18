"""
Request Handler — T7.5.10 fix

process() now accepts an optional `content` parameter.
When the caller (VaultWatcher._check_file) passes the already-read
file content, process() uses it directly instead of reading the file
again. This eliminates the TOCTOU race condition where Obsidian's
autosave could modify the file between the watcher's status check
and process()'s own re-read, causing the status check to fail.

If content is not passed (e.g. called from other contexts), the
function falls back to reading the file itself — backward compatible.
"""

import logging
from datetime import datetime
from pathlib import Path

from providers.provider_router import ProviderRouter
from providers.base_provider import Message, ProviderError, ProviderWebUIHandoff
from providers.model_registry import estimate_tokens
from memory.context_manager import ContextManager
from watcher.frontmatter_parser import FrontmatterParser
from watcher.content_chunker import ContentChunker

logger = logging.getLogger("watcher")


class RequestHandler:

    def __init__(
        self,
        vault_path:    str,
        router:        ProviderRouter,
        system_prompt: str = "",
    ):
        self._vault         = Path(vault_path)
        self._router        = router
        self._system_prompt = system_prompt or self._default_system_prompt()
        self._ctx_mgr       = ContextManager(router.registry)
        self._chunker       = ContentChunker(max_tokens=3000)

    # ------------------------------------------------------------------
    # Main entry — called by VaultWatcher for status: pending
    # T7.5.10: accepts pre-read content to avoid re-reading the file
    # ------------------------------------------------------------------

    def process(
        self,
        note_path: str,
        request:   str,
        content:   str | None = None,   # T7.5.10: pass pre-read content
        project:   str | None = None,
    ) -> bool:
        full_path = self._vault / note_path
        if not full_path.exists():
            logger.error(f"[RequestHandler] Note not found: {note_path}")
            return False

        # T7.5.10: use provided content, or read if not provided
        if content is None:
            try:
                content = full_path.read_text(encoding="utf-8")
            except Exception as exc:
                logger.error(f"[RequestHandler] Could not read {note_path}: {exc}")
                return False

        fm_dict, body = FrontmatterParser.extract(content)

        status = fm_dict.get("assistant-status", "").strip().strip('"\'').lower()
        if status != "pending":
            logger.debug(f"[RequestHandler] Skipping {note_path} — status is '{status}' not 'pending'")
            return False

        logger.info(f"[RequestHandler] Processing: {note_path}")
        logger.info(f"[RequestHandler] Request: {request[:100]}")

        token_count = estimate_tokens([], body)

        try:
            if token_count > 3000:
                chunks = self._chunker.chunk_content(body)
                reply  = self._process_chunks(chunks, request, note_path)
            else:
                history = [Message(
                    role    = "user",
                    content = f"[Vault Note Context]\n\nFile: {note_path}\n\n{body}\n\n---\n\nRequest: {request}",
                )]
                reply = self._call_provider(history)

            if reply is None:
                raise ProviderError("All providers failed")

        except ProviderWebUIHandoff as handoff:
            logger.info(f"[RequestHandler] Web handoff triggered for: {note_path}")
            self._write_handoff_pending(full_path, fm_dict, body, handoff.packaged_prompt)
            return False

        except ProviderError as exc:
            logger.error(f"[RequestHandler] Provider error: {exc}")
            self._write_error(full_path, fm_dict, body, str(exc))
            return False

        return self._write_response(full_path, fm_dict, body, reply)

    # ------------------------------------------------------------------
    # Handoff return
    # ------------------------------------------------------------------

    def inject_handoff_return(self, note_path: str) -> bool:
        full_path = self._vault / note_path
        if not full_path.exists():
            return False

        try:
            content = full_path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.error(f"[RequestHandler] Could not read {note_path}: {exc}")
            return False

        fm_dict, body = FrontmatterParser.extract(content)

        if fm_dict.get("assistant-status", "").strip('"') != "handoff-pending":
            return False

        return_marker = "## User Web Handoff Return"
        if return_marker not in body:
            return False

        parts           = body.split(return_marker, 1)
        pasted_response = parts[1].strip() if len(parts) > 1 else ""
        if not pasted_response:
            return False

        handoff_marker = "## Assistant Web Handoff Prompt"
        clean_body     = body.split(handoff_marker)[0].rstrip() if handoff_marker in body else parts[0].rstrip()

        logger.info(f"[RequestHandler] Handoff return received for: {note_path}")
        return self._write_response(full_path, fm_dict, clean_body, pasted_response)

    # ------------------------------------------------------------------
    # Write helpers
    # ------------------------------------------------------------------

    def _write_response(self, full_path: Path, fm_dict: dict, body: str, reply: str) -> bool:
        timestamp        = datetime.now().strftime("%Y-%m-%d %H:%M")
        response_section = f"\n\n## Assistant Response\n\n**Generated:** {timestamp}\n\n{reply}\n"
        fm_dict["assistant-status"]    = "done"
        fm_dict["assistant-responded"] = timestamp
        try:
            updated = FrontmatterParser.build(fm_dict, body + response_section)
            full_path.write_text(updated, encoding="utf-8")
            logger.info(f"[RequestHandler] Response written to {full_path.name}")
            return True
        except Exception as exc:
            logger.error(f"[RequestHandler] Write failed: {exc}")
            return False

    def _write_handoff_pending(self, full_path: Path, fm_dict: dict, body: str, packaged_prompt: str) -> None:
        timestamp       = datetime.now().strftime("%Y-%m-%d %H:%M")
        handoff_section = (
            f"\n\n## Assistant Web Handoff Prompt\n\n"
            f"**Generated:** {timestamp}\n\n"
            f"Copy the block below and paste into any web AI.\n\n"
            f"```\n{packaged_prompt}\n```\n\n"
            f"---\n\n"
            f"## User Web Handoff Return\n\n"
            f"*(Paste the web AI response here, then set assistant-status back to pending)*\n"
        )
        fm_dict["assistant-status"]    = "handoff-pending"
        fm_dict["assistant-responded"] = timestamp
        fm_dict["assistant-provider"]  = "webui"
        try:
            updated = FrontmatterParser.build(fm_dict, body + handoff_section)
            full_path.write_text(updated, encoding="utf-8")
            logger.info(f"[RequestHandler] Handoff pending written to {full_path.name}")
        except Exception as exc:
            logger.error(f"[RequestHandler] Could not write handoff: {exc}")

    def _write_error(self, full_path: Path, fm_dict: dict, body: str, error_text: str) -> None:
        timestamp       = datetime.now().strftime("%Y-%m-%d %H:%M")
        error_section   = (
            f"\n\n## Assistant Response — Error\n\n"
            f"**Generated:** {timestamp}\n\n"
            f"Unable to process request:\n\n```\n{error_text[:500]}\n```\n\n"
            f"To retry: set `assistant-status` back to `pending`.\n"
        )
        fm_dict["assistant-status"]    = "error"
        fm_dict["assistant-responded"] = timestamp
        try:
            updated = FrontmatterParser.build(fm_dict, body + error_section)
            full_path.write_text(updated, encoding="utf-8")
        except Exception as exc:
            logger.error(f"[RequestHandler] Could not write error: {exc}")

    # ------------------------------------------------------------------
    # Provider calls
    # ------------------------------------------------------------------

    def _process_chunks(self, chunks: list[str], request: str, note_path: str) -> str | None:
        responses = []
        for i, chunk in enumerate(chunks, 1):
            history = [Message(
                role    = "user",
                content = f"[Part {i} of {len(chunks)}]\n\n{chunk}\n\n---\n\nRequest: {request}",
            )]
            reply = self._call_provider(history)
            if reply is None:
                return None
            responses.append(reply)

        if len(responses) == 1:
            return responses[0]

        combined = f"Combine these {len(responses)} responses into a unified summary:\n\n"
        for i, r in enumerate(responses, 1):
            combined += f"### Part {i}:\n{r}\n\n"
        return self._call_provider([Message(role="user", content=combined)])

    def _call_provider(self, history: list[Message]) -> str | None:
        try:
            reply, _ = self._router.generate(
                messages      = history,
                system_prompt = self._system_prompt,
                max_tokens    = 2048,
                temperature   = 0.7,
            )
            return reply
        except ProviderWebUIHandoff:
            raise
        except ProviderError as exc:
            logger.error(f"[RequestHandler] Provider error: {exc}")
            return None

    def _default_system_prompt(self) -> str:
        return (
            "You are a helpful AI assistant integrated with Obsidian. "
            "Help with analysis, summarization, research, planning, and knowledge management. "
            "Be concise and practical. Format responses clearly with sections and bullet points."
        )
