"""
Request Handler — refactor: agent loop wired in

Changes:
  - process() now calls run_agent_loop() instead of router.generate().
    Vault commands the model emits in its reply are executed autonomously,
    same as the terminal and plugin paths.
  - AgentContext is constructed with source_label="watcher" so episode
    entries are tagged [watcher-agent].
  - The model no longer prints raw "vault:read ..." text into vault notes
    because the loop executes those commands and feeds results back before
    the final reply is written.
  - _process_chunks() updated to use the agent loop per chunk.
  - content parameter kept from the TOCTOU fix (headless-fixes patch).
"""

import logging
from datetime import datetime
from pathlib import Path
import threading

from assistant_core.providers.provider_router import ProviderRouter
from assistant_core.providers.base_provider import Message, ProviderError, ProviderWebUIHandoff
from assistant_core.providers.model_registry import estimate_tokens
from assistant_core.watcher.frontmatter_parser import FrontmatterParser
from assistant_core.watcher.content_chunker import ContentChunker
from assistant_core.agent_loop import AgentContext, run_agent_loop
from assistant_core import editing   # M9 — shared edit helpers (proposal staging)

logger = logging.getLogger("watcher")


def _truthy(value: str) -> bool:
    """Interpret a frontmatter string value as a boolean (private: true, etc.)."""
    return str(value).strip().strip('"\'').lower() in ("true", "yes", "1", "on")


class RequestHandler:

    def __init__(
        self,
        vault_path:    str,
        router:        ProviderRouter,
        registry       = None,   # ToolRegistry | None
        system_prompt: str = "",
    ):
        self._vault         = Path(vault_path)
        self._router        = router
        self._registry      = registry
        self._system_prompt = system_prompt or self._default_system_prompt()
        self._chunker       = ContentChunker(max_tokens=3000)
        # Dummy lock — RequestHandler runs in a single thread (the watcher)
        self._history_lock  = threading.Lock()

    # ------------------------------------------------------------------
    # Main entry — called by VaultWatcher for status: pending
    # ------------------------------------------------------------------

    def process(
        self,
        note_path: str,
        request:   str,
        content:   str | None = None,
        project:   str | None = None,
    ) -> bool:
        full_path = self._vault / note_path
        if not full_path.exists():
            logger.error(f"[RequestHandler] Note not found: {note_path}")
            return False

        if content is None:
            try:
                content = full_path.read_text(encoding="utf-8")
            except Exception as exc:
                logger.error(f"[RequestHandler] Could not read {note_path}: {exc}")
                return False

        fm_dict, body = FrontmatterParser.extract(content)

        status = fm_dict.get("assistant-status", "").strip().strip('"\'').lower()
        if status != "pending":
            logger.debug(f"[RequestHandler] Skipping {note_path} — status '{status}'")
            return False

        # Milestone 10 — privacy routing from note frontmatter.
        private     = _truthy(fm_dict.get("private", ""))
        allow_webui = _truthy(fm_dict.get("allow-webui", ""))

        # M9 — edit intent stages a propose/commit edit; it never overwrites the body.
        if _truthy(fm_dict.get("assistant-edit", "")):
            return self._stage_edit(full_path, note_path, fm_dict, body, request, private)

        logger.info(f"[RequestHandler] Processing: {note_path}")
        logger.info(f"[RequestHandler] Request: {request[:100]} (private={private})")

        token_count = estimate_tokens([], body)

        try:
            if token_count > 3000:
                chunks = self._chunker.chunk_content(body)
                reply  = self._process_chunks(chunks, request, note_path, private, allow_webui)
            else:
                reply = self._run_agent(
                    user_input  = f"[Vault Note Context]\n\nFile: {note_path}\n\n{body}\n\n---\n\nRequest: {request}",
                    note_path   = note_path,
                    private     = private,
                    allow_webui = allow_webui,
                )

            if reply is None:
                raise ProviderError("All providers failed")

        except ProviderWebUIHandoff as handoff:
            logger.info(f"[RequestHandler] Web handoff for: {note_path}")
            self._write_handoff_pending(full_path, fm_dict, body, handoff.packaged_prompt)
            return False

        except ProviderError as exc:
            logger.error(f"[RequestHandler] Provider error: {exc}")
            err_text = str(exc)
            if private and not allow_webui:
                err_text += (
                    "\n\nThis note is marked `private: true`, so it only routes to providers "
                    "that do not train on data, and the WebUI handoff is disabled. "
                    "To allow a WebUI handoff (which would expose the content to a web AI), "
                    "add `allow-webui: true` to the frontmatter and set assistant-status back to pending."
                )
            self._write_error(full_path, fm_dict, body, err_text)
            return False

        return self._write_response(full_path, fm_dict, body, reply)

    # ------------------------------------------------------------------
    # M9 — edit staging (propose/commit). The watcher only STAGES a proposal;
    # the plugin is the single commit point. The note body is never overwritten.
    # ------------------------------------------------------------------

    def _stage_edit(self, full_path, note_path, fm_dict, body, request, private) -> bool:
        # Drop any stale proposal block left from a previous run.
        body = editing.strip_proposal_block(body)

        scope = (fm_dict.get("assistant-edit-scope", "whole-note") or "whole-note").strip().strip('"\'').lower()
        if scope not in ("section", "whole-note"):
            self._write_error(full_path, fm_dict, body,
                              f"Vault edits support 'section' or 'whole-note' scope only (got '{scope}').")
            return False

        if scope == "section":
            target = fm_dict.get("assistant-edit-target", "").strip().strip('"\'')
            original, found = editing.section_text(body, target)
            if not found:
                self._write_error(full_path, fm_dict, body,
                                  f"Could not find the heading '{target}' — check `assistant-edit-target`.")
                return False
            anchor = editing.make_anchor(target, original, body)
        else:
            original = body.strip()
            anchor   = editing.make_anchor(None, original, body)

        if not original.strip():
            self._write_error(full_path, fm_dict, body, "Nothing to edit — the target region is empty.")
            return False

        logger.info(f"[RequestHandler] Staging edit — scope={scope} private={private} ({len(original)} chars)")
        messages = [Message(role="user", content=f"Instruction: {request}\n\nRegion to revise:\n{original}")]
        try:
            reply, used = self._router.generate(
                messages, system_prompt=editing.EDIT_SYSTEM, private=private, allow_webui=False,
            )
        except (ProviderError, ProviderWebUIHandoff) as exc:
            logger.warning(f"[RequestHandler] Edit providers exhausted: {exc}")
            extra = ""
            if private:
                extra = (" This note is `private: true`, so only no-train providers were tried. "
                         "Paste a revised version manually, or relax privacy to allow more providers.")
            self._write_error(full_path, fm_dict, body, f"No provider available for this edit.{extra}")
            return False

        proposal = editing.make_proposal(
            note_path=note_path, scope=scope, intent=request,
            original_text=original, replacement=editing.clean_edit_reply(reply),
            anchor=anchor, source="vault", provider=used,
        )
        return self._write_proposal(full_path, fm_dict, body, proposal)

    def _write_proposal(self, full_path, fm_dict, body, proposal) -> bool:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        fm_dict["assistant-status"]    = "proposal-pending"
        fm_dict["assistant-responded"] = timestamp
        try:
            # Body preserved untouched; the proposal block is appended for the plugin.
            updated = FrontmatterParser.build(fm_dict, body + editing.render_proposal_block(proposal))
            full_path.write_text(updated, encoding="utf-8")
            logger.info(f"[RequestHandler] Edit proposal staged in {full_path.name}")
        except Exception as exc:
            logger.error(f"[RequestHandler] Could not stage proposal: {exc}")
        return False   # not 'done' — status is proposal-pending; the plugin commits

    # ------------------------------------------------------------------
    # Agent loop wrapper
    # ------------------------------------------------------------------

    def _run_agent(
        self,
        user_input:  str,
        note_path:   str,
        private:     bool = False,
        allow_webui: bool = False,
    ) -> str | None:
        """
        Run the shared agent loop for one watcher request.
        The model can issue vault commands; they are executed and fed back
        before the final reply is written to the vault note.
        """
        history: list[Message] = []

        ctx = AgentContext(
            user_input        = user_input,
            history           = history,
            history_lock      = self._history_lock,
            router            = self._router,
            registry          = self._registry,
            memory            = None,       # no episode logging from watcher path
            ctx_mgr           = None,       # no context trimming for single-turn watcher
            system_prompt     = self._system_prompt,
            max_tokens        = 2048,
            temperature       = 0.7,
            provider_override = None,
            ep_vault_fn       = None,
            ep_error_fn       = None,
            tools_used        = [],
            source_label      = "watcher",
            private                = private,
            allow_webui_on_private = allow_webui,
            max_steps              = self._router.config.get("max_agent_steps", 10),
            config                 = self._router.config,
            rag                    = None,
        )

        try:
            reply, _ = run_agent_loop(ctx)
            return reply
        except ProviderWebUIHandoff:
            raise
        except ProviderError:
            raise
        except Exception as exc:
            logger.error(f"[RequestHandler] Agent loop error: {exc}")
            return None

    # ------------------------------------------------------------------
    # Chunked processing
    # ------------------------------------------------------------------

    def _process_chunks(
        self,
        chunks:      list[str],
        request:     str,
        note_path:   str,
        private:     bool = False,
        allow_webui: bool = False,
    ) -> str | None:
        responses = []
        for i, chunk in enumerate(chunks, 1):
            logger.info(f"[RequestHandler] Processing chunk {i}/{len(chunks)}")
            user_input = f"[Part {i} of {len(chunks)}]\n\n{chunk}\n\n---\n\nRequest: {request}"
            reply = self._run_agent(
                user_input=user_input, note_path=note_path,
                private=private, allow_webui=allow_webui,
            )
            if reply is None:
                return None
            responses.append(reply)

        if len(responses) == 1:
            return responses[0]

        # Combine chunk responses
        combined = f"Combine these {len(responses)} responses into a unified summary:\n\n"
        for i, r in enumerate(responses, 1):
            combined += f"### Part {i}:\n{r}\n\n"

        return self._run_agent(
            user_input=combined, note_path=note_path,
            private=private, allow_webui=allow_webui,
        )

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

    def _write_response(
        self,
        full_path: Path,
        fm_dict:   dict,
        body:      str,
        reply:     str,
    ) -> bool:
        timestamp        = datetime.now().strftime("%Y-%m-%d %H:%M")
        response_section = (
            f"\n\n## Assistant Response\n\n"
            f"**Generated:** {timestamp}\n\n{reply}\n"
        )
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

    def _write_handoff_pending(
        self,
        full_path:       Path,
        fm_dict:         dict,
        body:            str,
        packaged_prompt: str,
    ) -> None:
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

    def _write_error(
        self,
        full_path:  Path,
        fm_dict:    dict,
        body:       str,
        error_text: str,
    ) -> None:
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

    def _default_system_prompt(self) -> str:
        """Fallback used only when no prompt is supplied (e.g. standalone watcher.py)."""
        return (
            "You are a helpful AI assistant integrated with Obsidian. "
            "Help with analysis, summarization, research, planning, and knowledge management. "
            "Be concise and practical. Format responses clearly with sections and bullet points. "
            "When you need information from the vault, use vault:read or vault:search — "
            "the system will execute those commands and show you the results."
        )
