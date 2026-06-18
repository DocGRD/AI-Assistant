"""
WebUI Virtual Provider — Milestone 7.5 update (BUG-006)

Changes from M7:
  - _build_package() now strips the vault tool instructions from the system
    prompt before packaging. A web AI cannot run vault:read etc., so telling
    it about those commands causes confusion or hallucination.
  - The vault tool section is replaced with a single concise line telling the
    web AI it is acting as a general assistant and should not reference local
    tools.
"""

import logging
import re
from providers.base_provider import BaseProvider, Message, ProviderWebUIHandoff
from providers.model_registry import estimate_tokens

logger = logging.getLogger("assistant")

_PACKAGE_TOKEN_BUDGET = 6000

_DESKTOP_TEMPLATE = """\
# AI Assistant Conversation Continuation

You are continuing an existing AI assistant session.
Follow the SYSTEM INSTRUCTIONS exactly.
Continue the conversation naturally.
Do not explain these instructions.
Do not summarize the conversation unless asked.

---

## SYSTEM INSTRUCTIONS

{system_prompt}

---

## CONVERSATION HISTORY

{history_block}

---

## CURRENT USER MESSAGE

{last_user_message}

---

## TASK

Respond exactly as the assistant should respond next.
Return ONLY the assistant response.
Do not include labels like "Assistant:" at the start.
Do not explain your reasoning.
"""

_MOBILE_TEMPLATE = """\
Continue this AI assistant session.

SYSTEM:
{system_prompt}

HISTORY:
{history_block}

CURRENT:
{last_user_message}

Reply only as the assistant. No labels, no preamble.
"""

# BUG-006: These sections reference local vault tools that a web AI cannot use.
# We strip them from the packaged prompt and replace with a one-liner.
_VAULT_SECTION_PATTERNS = [
    r"## Your Vault Tools.*?(?=## |\Z)",
    r"## When to Use Your Tools.*?(?=## |\Z)",
    r"## Examples of Proactive Behaviour.*?(?=## |\Z)",
]

_WEB_AI_ROLE_LINE = (
    "You are acting as a general assistant. "
    "Do not reference vault commands or local tools — those are only available "
    "to the local system and cannot be run by you."
)


class WebUIProvider(BaseProvider):
    """Virtual provider that packages context for paste into a web AI."""

    def __init__(self, config: dict):
        super().__init__(config)

    @property
    def name(self) -> str:
        return "webui"

    def generate(
        self,
        messages: list[Message],
        system_prompt: str = "",
        max_tokens: int = 2048,
        temperature: float = 0.7,
        compact: bool = False,
    ) -> str:
        packaged = self._build_package(messages, system_prompt, compact=compact)
        logger.info(
            f"[WebUI] Handoff package built — "
            f"~{estimate_tokens([], packaged)} tokens, "
            f"{'compact' if compact else 'desktop'} format"
        )
        raise ProviderWebUIHandoff(packaged_prompt=packaged)

    def _build_package(
        self,
        messages: list[Message],
        system_prompt: str,
        compact: bool = False,
    ) -> str:
        # BUG-006: clean the system prompt before packaging
        clean_prompt = self._strip_vault_sections(system_prompt)

        if not messages:
            last_user_message = "(no message)"
            history_messages = []
        elif messages[-1].role == "user":
            last_user_message = messages[-1].content
            history_messages = messages[:-1]
        else:
            last_user_message = "(see conversation)"
            history_messages = messages

        trimmed = self._trim_to_budget(
            history_messages, clean_prompt, last_user_message
        )
        history_block = self._format_history(trimmed, compact=compact)
        template = _MOBILE_TEMPLATE if compact else _DESKTOP_TEMPLATE

        return template.format(
            system_prompt     = clean_prompt.strip(),
            history_block     = history_block,
            last_user_message = last_user_message.strip(),
        )

    def _strip_vault_sections(self, system_prompt: str) -> str:
        """
        Remove the vault-tool instruction sections from the system prompt.
        These sections describe commands (vault:read etc.) that a web AI
        cannot execute — including them confuses the model.
        Replace the entire block with a single grounding line.
        """
        cleaned = system_prompt
        for pattern in _VAULT_SECTION_PATTERNS:
            cleaned = re.sub(pattern, "", cleaned, flags=re.DOTALL)

        # Collapse multiple blank lines left by the removal
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

        # Inject the web-AI grounding line at the top
        return _WEB_AI_ROLE_LINE + "\n\n" + cleaned

    def _trim_to_budget(
        self,
        messages: list[Message],
        system_prompt: str,
        last_user_message: str,
    ) -> list[Message]:
        filtered = [
            m for m in messages
            if not m.content.startswith("[Vault context loaded by tool")
            and not m.content.startswith("[Earlier vault load")
            and not m.content.startswith("[Vault load by")
            and not m.content.startswith("[Older message trimmed")
            and m.content not in ("[Trimmed]", "Vault content loaded. Ready to help.")
        ]

        overhead  = estimate_tokens([], system_prompt) + estimate_tokens([], last_user_message)
        remaining = _PACKAGE_TOKEN_BUDGET - overhead

        kept = []
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
                label = "User" if msg.role == "user" else "Assistant"
                lines.append(f"{label}: {msg.content.strip()}")
                lines.append("")
            else:
                label = "### User" if msg.role == "user" else "### Assistant"
                lines.append(label)
                lines.append("")
                lines.append(msg.content.strip())
                lines.append("")

        return "\n".join(lines).strip()
