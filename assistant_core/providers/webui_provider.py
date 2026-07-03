"""
WebUI Virtual Provider — Milestone 8 refactor

Changes:
  1. Loads AI/System/WebUI-Prompt.md from the vault as the web AI
     partner instructions instead of stripping the system prompt.
     This is a clean separate prompt with no vault syntax — no more
     contradictory instructions.
  2. Falls back to DEFAULT_WEBUI_PROMPT if the vault file is missing.
  3. vault_path is now a constructor parameter so the provider can
     read the vault file.
  4. The packaged prompt format is cleaner — system instructions come
     from WebUI-Prompt.md, and the user's personal context (from
     User-Profile etc.) is appended as a separate CONTEXT section.
"""

import logging
import re
from pathlib import Path
from assistant_core.providers.base_provider import BaseProvider, Message, ProviderWebUIHandoff
from assistant_core.providers.model_registry import estimate_tokens

logger = logging.getLogger("assistant")

_PACKAGE_TOKEN_BUDGET  = 6000
WEBUI_PROMPT_VAULT_PATH = "AI/System/WebUI-Prompt.md"

DEFAULT_WEBUI_PROMPT = """You are a research and thinking partner continuing an AI assistant session on behalf of a user.

The user has a local knowledge management system (Obsidian vault) that you cannot access directly. They will provide relevant context when available. Your job is to think, reason, and answer using the context provided plus your own knowledge.

Answer the question directly and clearly. If your answer would improve with a specific vault search, say so in plain English at the end — do not emit commands.

Honesty: you cannot see the user's vault. Never invent the contents of their notes, files, dates, quotes, or citations — answer only from the context they pasted plus your general knowledge, keep those separate, and say so plainly when you're unsure. You have no tools, so never claim to have searched, read, or verified anything.

Be concise, practical, and specific. The user values precision over verbosity."""

_DESKTOP_TEMPLATE = """\
# AI Assistant — Web Research Session

{web_ai_instructions}

---

## USER CONTEXT

{user_context}

---

## CONVERSATION HISTORY

{history_block}

---

## CURRENT QUESTION

{last_user_message}

---

## INSTRUCTIONS

Respond directly to CURRENT QUESTION.
Use CONVERSATION HISTORY for context.
Use USER CONTEXT to personalise your answer.
Return ONLY your response — no preamble, no labels.
"""

_MOBILE_TEMPLATE = """\
{web_ai_instructions}

CONTEXT:
{user_context}

HISTORY:
{history_block}

QUESTION:
{last_user_message}

Reply directly. No preamble.
"""


class WebUIProvider(BaseProvider):
    """Virtual provider that packages context for paste into a web AI."""

    def __init__(self, config: dict):
        super().__init__(config)
        self._vault_path = config.get("vault_path", "")

    @property
    def name(self) -> str:
        return "webui"

    def generate(
        self,
        messages:      list[Message],
        system_prompt: str  = "",
        max_tokens:    int  = 2048,
        temperature:   float = 0.7,
        compact:       bool  = False,
    ) -> str:
        packaged = self._build_package(messages, system_prompt, compact=compact)
        logger.info(
            f"[WebUI] Handoff package built — "
            f"~{estimate_tokens([], packaged)} tokens, "
            f"{'compact' if compact else 'desktop'} format"
        )
        raise ProviderWebUIHandoff(packaged_prompt=packaged)

    def _load_webui_prompt(self) -> str:
        """Load AI/System/WebUI-Prompt.md from vault. Fall back to default."""
        if not self._vault_path:
            return DEFAULT_WEBUI_PROMPT

        prompt_path = Path(self._vault_path) / WEBUI_PROMPT_VAULT_PATH
        if not prompt_path.exists():
            logger.debug("[WebUI] WebUI-Prompt.md not found — using default")
            return DEFAULT_WEBUI_PROMPT

        try:
            content = prompt_path.read_text(encoding="utf-8")
            # Strip the YAML/Markdown header comments (lines starting with # or *)
            lines = content.splitlines()
            body_lines = []
            in_header = True
            for line in lines:
                if in_header and (line.startswith("#") or line.startswith("*") or line.strip() == "---" or not line.strip()):
                    # Skip header until we hit actual content
                    if line.startswith("You ") or line.startswith("Answer") or line.startswith("Be "):
                        in_header = False
                        body_lines.append(line)
                else:
                    in_header = False
                    body_lines.append(line)

            result = "\n".join(body_lines).strip()
            logger.info(f"[WebUI] Loaded WebUI-Prompt.md ({len(result)} chars)")
            return result if result else DEFAULT_WEBUI_PROMPT
        except Exception as exc:
            logger.warning(f"[WebUI] Could not read WebUI-Prompt.md: {exc}")
            return DEFAULT_WEBUI_PROMPT

    def _extract_user_context(self, system_prompt: str) -> tuple[str, str]:
        """
        Split the system prompt into:
        - web AI instructions (from WebUI-Prompt.md — loaded separately)
        - user context (User Profile, Learned Facts, etc.)

        Returns (web_ai_instructions, user_context).
        The web_ai_instructions come from the vault file, not the system prompt.
        User context is extracted from the ## Persistent Memory section.
        """
        web_ai_instructions = self._load_webui_prompt()

        # Extract the Persistent Memory section from the system prompt
        # This contains User Profile, Learned Facts, etc.
        user_context = ""
        if "## Persistent Memory" in system_prompt:
            # Take everything from ## Persistent Memory onwards
            memory_start = system_prompt.index("## Persistent Memory")
            user_context = system_prompt[memory_start:].strip()
        elif "### User Profile" in system_prompt:
            profile_start = system_prompt.index("### User Profile")
            user_context = system_prompt[profile_start:].strip()

        if not user_context:
            user_context = "(No personal context available)"

        return web_ai_instructions, user_context

    def _build_package(
        self,
        messages:      list[Message],
        system_prompt: str,
        compact:       bool = False,
    ) -> str:
        web_ai_instructions, user_context = self._extract_user_context(system_prompt)

        if not messages:
            last_user_message = "(no message)"
            history_messages  = []
        elif messages[-1].role == "user":
            last_user_message = messages[-1].content
            history_messages  = messages[:-1]
        else:
            last_user_message = "(see conversation)"
            history_messages  = messages

        trimmed      = self._trim_to_budget(history_messages, user_context, last_user_message)
        history_block = self._format_history(trimmed, compact=compact)
        template     = _MOBILE_TEMPLATE if compact else _DESKTOP_TEMPLATE

        return template.format(
            web_ai_instructions = web_ai_instructions.strip(),
            user_context        = user_context.strip(),
            history_block       = history_block,
            last_user_message   = last_user_message.strip(),
        )

    def _trim_to_budget(
        self,
        messages:          list[Message],
        user_context:      str,
        last_user_message: str,
    ) -> list[Message]:
        filtered = [
            m for m in messages
            if not m.content.startswith("[Vault context loaded by tool")
            and not m.content.startswith("[Earlier vault load")
            and not m.content.startswith("[Vault load by")
            and not m.content.startswith("[Older message trimmed")
            and not m.content.startswith("[Tool execution complete")
            and not m.content.startswith("[Tool result for")
            and not m.content.startswith("[SYSTEM HINT]")
            and not m.content.startswith("[Blocked:")
            and m.content not in ("[Trimmed]", "Vault content loaded. Ready to help.")
        ]

        overhead  = (estimate_tokens([], user_context)
                     + estimate_tokens([], last_user_message))
        remaining = _PACKAGE_TOKEN_BUDGET - overhead
        kept      = []

        for msg in reversed(filtered):
            cost = estimate_tokens([msg], "")
            if remaining - cost < 0:
                break
            kept.insert(0, msg)
            remaining -= cost

        if len(kept) < len(filtered):
            kept.insert(0, Message(
                role    = "user",
                content = "[Earlier conversation omitted to fit context window]"
            ))

        return kept

    def _format_history(self, messages: list[Message], compact: bool = False) -> str:
        if not messages:
            return "(no prior conversation)"

        lines = []
        for msg in messages:
            if compact:
                label = "You" if msg.role == "user" else "Assistant"
                lines.append(f"{label}: {msg.content.strip()}")
                lines.append("")
            else:
                label = "### You" if msg.role == "user" else "### Assistant"
                lines.append(label)
                lines.append("")
                lines.append(msg.content.strip())
                lines.append("")

        return "\n".join(lines).strip()
