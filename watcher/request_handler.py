"""
Request Handler — Process vault watcher requests.

Workflow:
    1. Receive: note path + request from frontmatter
    2. Load: full note content
    3. Estimate: token count, chunk if necessary
    4. Call: ProviderRouter.generate() with content (chunked if needed)
    5. Append: response to note under "## Assistant Response"
    6. Update: frontmatter status to done + timestamp
"""

import logging
from datetime import datetime
from pathlib import Path

from providers.provider_router import ProviderRouter
from providers.base_provider import Message, ProviderError
from providers.model_registry import estimate_tokens
from memory.context_manager import ContextManager
from watcher.frontmatter_parser import FrontmatterParser
from watcher.content_chunker import ContentChunker

logger = logging.getLogger("watcher")


class RequestHandler:
    """Handles processing and responding to vault watcher requests."""

    def __init__(self, vault_path: str, router: ProviderRouter, system_prompt: str = ""):
        self._vault = Path(vault_path)
        self._router = router
        self._system_prompt = system_prompt or self._default_system_prompt()
        self._ctx_mgr = ContextManager(router.registry)
        self._chunker = ContentChunker(max_tokens=3000)  # Leave room for response

    def process(self, note_path: str, request: str, project: str | None = None) -> bool:
        """
        Process a watcher request.

        Args:
            note_path: Relative path to note from vault root (e.g. "Projects/my-project.md")
            request: The user's request string from frontmatter
            project: Optional project name for memory context

        Returns:
            True if successful, False otherwise
        """
        full_path = self._vault / note_path
        if not full_path.exists():
            logger.error(f"[RequestHandler] Note not found: {note_path}")
            return False

        try:
            content = full_path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.error(f"[RequestHandler] Could not read {note_path}: {exc}")
            return False

        # Extract frontmatter and body
        fm_dict, body = FrontmatterParser.extract(content)

        # Check status
        if fm_dict.get("assistant-status") != "pending":
            logger.debug(f"[RequestHandler] Skipping {note_path} — status not pending")
            return False

        logger.info(f"[RequestHandler] Processing request in {note_path}")
        logger.info(f"[RequestHandler] Request: {request[:100]}")

        # Estimate token count and chunk if necessary
        token_count = estimate_tokens([], body)
        logger.info(f"[RequestHandler] Content size: ~{token_count} tokens")
        
        try:
            if token_count > 3000:
                logger.info(f"[RequestHandler] Content too large, chunking into smaller pieces...")
                chunks = self._chunker.chunk_content(body)
                logger.info(f"[RequestHandler] Chunked into {len(chunks)} pieces")
                reply = self._process_chunks(chunks, request, note_path)
            else:
                # Single request for smaller content
                history = [
                    Message(
                        role="user",
                        content=f"[Vault Note Context]\n\nFile: {note_path}\n\n{body}\n\n---\n\nRequest: {request}",
                    )
                ]
                reply = self._call_provider(history)

            if reply is None:
                # Provider error — write error message to note
                raise ProviderError("All providers failed or were unavailable")
        except ProviderError as exc:
            logger.error(f"[RequestHandler] Provider error: {exc}")
            
            # Write error response to note
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            error_msg = f"""⚠️ **Assistant Response — Error**

**Generated:** {timestamp}

Unable to process this request due to a provider error:

```
{str(exc)[:500]}
```

**Common solutions:**
- If the note is very large, try breaking it into smaller notes
- Wait a few minutes and try again (provider might be overloaded)
- Check that API keys are valid in settings.json

To retry: Change `assistant-status` back to `pending` and modify the note to trigger a rescan."""

            try:
                fm_dict["assistant-status"] = "error"
                fm_dict["assistant-responded"] = timestamp
                updated_content = FrontmatterParser.build(fm_dict, body + "\n\n## Assistant Response\n\n" + error_msg)
                full_path.write_text(updated_content, encoding="utf-8")
                logger.info(f"[RequestHandler] Error message written to {note_path}")
            except Exception as write_exc:
                logger.error(f"[RequestHandler] Could not write error: {write_exc}")
            
            return False

        # Append response to note
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        response_section = f"\n\n## Assistant Response\n\n**Generated:** {timestamp}\n\n{reply}\n"

        try:
            # Update frontmatter
            fm_dict["assistant-status"] = "done"
            fm_dict["assistant-responded"] = timestamp

            # Build updated content
            updated_content = FrontmatterParser.build(fm_dict, body + response_section)

            # Write back
            full_path.write_text(updated_content, encoding="utf-8")
            logger.info(f"[RequestHandler] Response written to {note_path}")
            return True

        except Exception as exc:
            logger.error(f"[RequestHandler] Could not write response: {exc}")
            return False

    def _process_chunks(self, chunks: list[str], request: str, note_path: str) -> str | None:
        """
        Process multiple chunks and combine results.
        
        Returns:
            Combined response, or None if error
        """
        chunk_responses = []
        
        for i, chunk in enumerate(chunks, 1):
            logger.info(f"[RequestHandler] Processing chunk {i}/{len(chunks)}")
            history = [
                Message(
                    role="user",
                    content=f"[Part {i} of {len(chunks)}]\n\n{chunk}\n\n---\n\nRequest: {request}",
                )
            ]
            reply = self._call_provider(history)
            if reply is None:
                return None  # Provider error
            chunk_responses.append(reply)
        
        # If single chunk, return as-is
        if len(chunk_responses) == 1:
            return chunk_responses[0]
        
        # Combine multiple chunk responses
        combined_prompt = f"""Please combine these {len(chunk_responses)} responses into a cohesive summary:

"""
        for i, response in enumerate(chunk_responses, 1):
            combined_prompt += f"\n### Part {i} Summary:\n{response}\n"
        
        combined_prompt += "\nNow provide a unified summary combining all parts:"
        
        history = [Message(role="user", content=combined_prompt)]
        final_reply = self._call_provider(history)
        return final_reply

    def _call_provider(self, history: list[Message]) -> str | None:
        """
        Call the provider and handle errors.
        
        Returns:
            Response text, or None if error
        """
        try:
            reply = self._router.generate(
                messages=history,
                system_prompt=self._system_prompt,
                max_tokens=2048,
                temperature=0.7,
            )
            return reply
        except ProviderError as exc:
            logger.error(f"[RequestHandler] Provider error: {exc}")
            return None

    def _default_system_prompt(self) -> str:
        """Default system prompt for watcher requests."""
        return """You are a helpful AI assistant integrated with Obsidian.
You help with analysis, summarization, research, planning, and knowledge management.
Be concise, accurate, and practical. Use the vault note content provided to give specific answers.
When responding to vault note requests, format your response clearly with sections and bullet points."""
