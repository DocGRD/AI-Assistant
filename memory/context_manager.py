"""
Context Window Manager — Milestone 4C
======================================
Controls what stays in the conversation history and what gets trimmed or
summarised, so the assistant never hits a token limit mid-conversation.

Rules (applied in this order):
  1. Never trim user/assistant chat pairs below KEEP_CHAT_TURNS.
  2. Vault tool output messages older than the most recent load of each
     tool are collapsed to a one-line summary.
  3. If estimated tokens still exceed the SAFE_THRESHOLD of the active
     provider's TPM limit, trim the oldest vault context blocks.
  4. If still over limit, trim the oldest chat turns (down to MIN_CHAT_TURNS).

Usage:
    manager = ContextManager(model_registry)
    clean_history = manager.trim(history, active_provider, system_prompt, max_response_tokens)
"""

import logging
from providers.base_provider import Message
from providers.model_registry import ModelRegistry, estimate_tokens

logger = logging.getLogger("assistant")

# How many recent user/assistant chat turns to always preserve
KEEP_CHAT_TURNS = 10
MIN_CHAT_TURNS  = 4   # absolute floor — never go below this

# Trim when estimated tokens exceed this fraction of the provider's TPM limit
SAFE_THRESHOLD  = 0.80   # 80%

# Marker prefix used when vault tool outputs are injected into history
VAULT_MARKER = "[Vault context loaded by tool '"


class ContextManager:
    """Trims conversation history to fit within the active provider's limits."""

    def __init__(self, model_registry: ModelRegistry):
        self._registry = model_registry

    def trim(
        self,
        history: list[Message],
        active_provider: str,
        system_prompt: str = "",
        max_response_tokens: int = 2048,
    ) -> list[Message]:
        """
        Return a trimmed copy of history that fits within the active provider's limits.
        The original list is never mutated.

        Args:
            history:             Full conversation history.
            active_provider:     Name of the provider that will receive this request.
            system_prompt:       System prompt (counted toward token estimate).
            max_response_tokens: Tokens reserved for the response.

        Returns:
            Trimmed list of Message objects.
        """
        if not history:
            return history

        spec = self._registry.spec(active_provider)
        if spec is None:
            # Unknown provider — return unchanged
            return history

        # Limit to the lower of: TPM cap, context window (minus response budget)
        safe_input_limit = min(
            int(spec.tpm_limit * SAFE_THRESHOLD),
            spec.context_window - max_response_tokens,
        )

        current_estimate = estimate_tokens(history, system_prompt)

        if current_estimate <= safe_input_limit:
            return history  # nothing to do

        logger.info(
            f"[ContextManager] {current_estimate} tokens exceeds safe limit "
            f"{safe_input_limit} for {active_provider} — trimming..."
        )

        working = list(history)  # work on a copy

        # ── Pass 1: Collapse older vault tool outputs ────────────────────
        working = self._collapse_old_vault_blocks(working)
        current_estimate = estimate_tokens(working, system_prompt)
        if current_estimate <= safe_input_limit:
            logger.info(f"[ContextManager] After vault collapse: ~{current_estimate} tokens — OK")
            return working

        # ── Pass 2: Trim oldest vault blocks entirely ────────────────────
        working = self._remove_vault_blocks(working, safe_input_limit, system_prompt)
        current_estimate = estimate_tokens(working, system_prompt)
        if current_estimate <= safe_input_limit:
            logger.info(f"[ContextManager] After vault removal: ~{current_estimate} tokens — OK")
            return working

        # ── Pass 3: Trim oldest chat turns (down to MIN_CHAT_TURNS) ─────
        working = self._trim_chat_turns(working, safe_input_limit, system_prompt)
        current_estimate = estimate_tokens(working, system_prompt)
        logger.info(f"[ContextManager] After chat trim: ~{current_estimate} tokens")

        return working

    # ------------------------------------------------------------------
    # Internal passes
    # ------------------------------------------------------------------

    def _is_vault_block(self, msg: Message) -> bool:
        return msg.role == "user" and msg.content.startswith(VAULT_MARKER)

    def _vault_tool_name(self, msg: Message) -> str:
        """Extract tool name from a vault context message."""
        try:
            # Content starts with "[Vault context loaded by tool 'read_note']"
            return msg.content.split("'")[1]
        except IndexError:
            return "unknown"

    def _collapse_old_vault_blocks(self, history: list[Message]) -> list[Message]:
        """
        For each tool, keep only the MOST RECENT load in full.
        Earlier loads of the same tool become a one-line summary.
        """
        # Find the index of the last load for each tool
        last_load: dict[str, int] = {}
        for i, msg in enumerate(history):
            if self._is_vault_block(msg):
                last_load[self._vault_tool_name(msg)] = i

        result = []
        for i, msg in enumerate(history):
            if self._is_vault_block(msg):
                tool = self._vault_tool_name(msg)
                if i < last_load[tool]:
                    # Replace with summary
                    char_count = len(msg.content)
                    result.append(Message(
                        role    = "user",
                        content = f"[Earlier vault load by '{tool}' — {char_count} chars — collapsed to save context]",
                    ))
                    # Keep the paired assistant acknowledgement as a stub
                    continue
                else:
                    result.append(msg)
            else:
                result.append(msg)

        return result

    def _remove_vault_blocks(
        self,
        history: list[Message],
        limit: int,
        system_prompt: str,
    ) -> list[Message]:
        """Remove vault block pairs (user+assistant) oldest first until under limit."""
        working = list(history)

        for i in range(len(working)):
            if estimate_tokens(working, system_prompt) <= limit:
                break
            msg = working[i]
            if self._is_vault_block(msg):
                tool = self._vault_tool_name(msg)
                working[i] = Message(
                    role    = "user",
                    content = f"[Vault load by '{tool}' removed to save context]",
                )
                # Stub the paired assistant message if it follows
                if i + 1 < len(working) and working[i + 1].role == "assistant":
                    working[i + 1] = Message(
                        role    = "assistant",
                        content = "[Acknowledged vault load — content removed from context]",
                    )

        return working

    def _trim_chat_turns(
        self,
        history: list[Message],
        limit: int,
        system_prompt: str,
    ) -> list[Message]:
        """
        Remove the oldest user/assistant chat pairs until under limit
        or until MIN_CHAT_TURNS remains.
        """
        # Identify pure chat message indices (not vault blocks)
        chat_indices = [
            i for i, msg in enumerate(history)
            if not self._is_vault_block(msg)
        ]

        # Group into pairs; preserve the newest KEEP_CHAT_TURNS
        pairs = []
        for j in range(0, len(chat_indices) - 1, 2):
            pairs.append((chat_indices[j], chat_indices[j + 1]))

        working = list(history)
        removable = pairs[: max(0, len(pairs) - MIN_CHAT_TURNS)]

        for user_i, asst_i in removable:
            if estimate_tokens(working, system_prompt) <= limit:
                break
            working[user_i] = Message(
                role="user", content="[Older message trimmed to save context]"
            )
            working[asst_i] = Message(
                role="assistant", content="[Trimmed]"
            )

        return working

    def report(
        self,
        history: list[Message],
        active_provider: str,
        system_prompt: str = "",
    ) -> str:
        """Return a one-line context status for the 'status' command."""
        est = estimate_tokens(history, system_prompt)
        spec = self._registry.spec(active_provider)
        if spec:
            pct = int(est / spec.tpm_limit * 100)
            return (
                f"~{est:,} tokens in history "
                f"({pct}% of {active_provider} TPM limit), "
                f"{len(history)} messages"
            )
        return f"~{est:,} tokens in history, {len(history)} messages"
