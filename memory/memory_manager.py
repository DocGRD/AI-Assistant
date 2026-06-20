"""
Memory Manager — refactor: system prompt lives in the vault

Changes:
  - SYSTEM_PROMPT_FILE = "AI/System/System-Prompt.md"
  - load_system_prompt() reads the prompt from the vault.
    If the file does not exist, seeds it from DEFAULT_SYSTEM_PROMPT
    and returns the default.
  - The prompt file is plain Markdown so the user can edit it in
    Obsidian without touching Python code.
  - All other methods unchanged.
"""

import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Default system prompt — written to vault on first run if missing.
# Kept here as the authoritative source-of-truth fallback.
# Edit AI/System/System-Prompt.md in Obsidian to customise.
# ---------------------------------------------------------------------------

DEFAULT_SYSTEM_PROMPT = """You are an AI development and study assistant integrated with an Obsidian vault. You have direct access to the vault through a set of tools. Use them proactively — do not wait to be asked.

## Your Vault Tools

You can interact with the vault at any time using these commands:

- vault:read <note name or path>   — Read the full text of any note
- vault:search <query>             — Full-text search across all notes
- vault:list [subfolder]           — Browse the vault folder structure
- vault:links <note name>          — Read a note plus all notes it wikilinks to
- vault:create <path>              — Write a new note (path on first line, content after)
- vault:update <path>              — Append content to an existing note
- vault:research <question>        — Generate an optimised prompt for an external web AI
- vault:summarise <path>           — Load a research note and summarise it

## Important: how vault commands work

When you include a vault: command on its own line in your reply, the system executes it automatically and shows you the result. Use the result in your next response.

### Path format rules

Put the full path on the FIRST LINE after vault:create or vault:update, then content on the lines that follow.

CORRECT:
vault:create AI/Memory/Projects/My-Project/Index.md
# My Project Index
Content goes here.

WRONG — path and content on the same line:
vault:create AI/Memory/Projects/My-Project/Index.md # Content here

### Note naming convention

Use hyphens to separate words in new note names. Do NOT use spaces or forward slashes as word separators in new paths.

CORRECT:  vault:create AI/Research/rocket-stove-design.md
WRONG:    vault:create AI/Research/rocket/stove/design.md

Existing folders with spaces (like "06 - Projects") are fine to reference.

### vault:import is not available in autonomous mode

Do NOT issue vault:import. It requires interactive paste. To save content you already have, use vault:create instead.

## When to use your tools

Before answering questions about topics that might be in the vault, search or read relevant notes first. Do not answer from general knowledge when specific vault knowledge exists.

Before writing code or plans, check AI/Memory/Projects/ for relevant context.

After significant decisions, offer to save them with vault:update.

When asked to help with this AI assistant project, read AI/System/Project-State.md first — it contains the full architecture and forward plan. You are being used to help build and improve yourself.

## Your Role

You help with software development, Scripture study, research, planning, and knowledge management. You are concise, accurate, and practical. When you don't know something, say so — then search the vault or generate a research prompt.

When the user types 'remember: <something>', acknowledge that the fact has been saved to Learned-Facts.md.
When vault content is loaded into context, use it to give specific, grounded answers."""


class MemoryManager:
    """Reads and writes the vault's AI/Memory/ folder."""

    MEMORY_ROOT        = "AI/Memory"
    PROFILE_FILE       = "AI/Memory/User-Profile.md"
    FACTS_FILE         = "AI/Memory/Facts/Learned-Facts.md"
    PROJECTS_DIR       = "AI/Memory/Projects"
    EPISODES_DIR       = "AI/Memory/Episodes"
    SYSTEM_DIR         = "AI/System"
    SYSTEM_PROMPT_FILE = "AI/System/System-Prompt.md"   # ← new

    def __init__(self, vault_path: str):
        self._vault    = Path(vault_path)
        self._ep_path: Path | None = None
        self._ensure_structure()

    # ------------------------------------------------------------------
    # Startup: folder structure and seed files
    # ------------------------------------------------------------------

    def _ensure_structure(self) -> None:
        for d in [
            self._vault / "AI" / "Memory" / "Facts",
            self._vault / "AI" / "Memory" / "Projects",
            self._vault / "AI" / "Memory" / "Episodes",
            self._vault / "AI" / "System",
        ]:
            d.mkdir(parents=True, exist_ok=True)

        self._seed_profile()
        self._seed_facts()
        # System-Prompt.md is seeded lazily in load_system_prompt()

    def _seed_profile(self) -> None:
        profile_path = self._vault / self.PROFILE_FILE
        if profile_path.exists():
            return
        profile_path.write_text(
            "# User Profile\n\n"
            "<!-- The assistant reads this file at every startup. -->\n"
            "<!-- Fill in your details so the assistant knows who it is working with. -->\n\n"
            "## Basic Information\n\n"
            "- **Name:** Glenn\n"
            "- **Primary OS:** Windows 11 (Linux planned)\n"
            "- **Python version:** 3.13.2\n\n"
            "## Active Projects\n\n"
            "- AI Assistant for Obsidian (this project)\n\n"
            "## Obsidian Vault Structure\n\n"
            "- 01 - God: Scripture, prayer, memorization\n"
            "- 02 - Marriage: Personal\n"
            "- 03 - Family: Family notes\n"
            "- 04 - Study and Teach: Scripture study, sermon notes (active: 1 John series)\n"
            "- 05 - Personal Growth: Emotions journal\n"
            "- 06 - Projects: Grok projects, technology\n"
            "- AI/: Assistant memory and system files\n\n"
            "## Preferences\n\n"
            "- Bible version: ESV\n"
            "- Hermeneutic: Spirit-led, Calvary Chapel-aligned, literal-contextual\n"
            "- Code style: Beginner-friendly, well-commented\n"
            "- Zero-cost constraint: All AI providers must remain on free tiers\n\n"
            "## Technology Stack\n\n"
            "- AI Assistant: Python 3.13, Groq + Google AI (free tiers)\n"
            "- Note-taking: Obsidian\n"
            "- Editor: VS Code\n",
            encoding="utf-8",
        )
        logger.info("[Memory] Created User-Profile.md template")

    def _seed_facts(self) -> None:
        facts_path = self._vault / self.FACTS_FILE
        if facts_path.exists():
            return
        facts_path.write_text(
            "# Learned Facts\n\n"
            "<!-- Things the assistant has been explicitly told to remember. -->\n"
            "<!-- Added automatically when you type: remember: <fact> -->\n\n",
            encoding="utf-8",
        )
        logger.info("[Memory] Created Learned-Facts.md template")

    # ------------------------------------------------------------------
    # System prompt — reads from vault, seeds if missing
    # ------------------------------------------------------------------

    def load_system_prompt(self) -> str:
        """
        Read the system prompt from AI/System/System-Prompt.md.

        If the file does not exist, write DEFAULT_SYSTEM_PROMPT to it
        and return the default. This seeds the file on first run so the
        user can find and edit it in Obsidian.

        Returns the raw prompt string (no memory context appended —
        the caller does that via build_system_prompt()).
        """
        prompt_path = self._vault / self.SYSTEM_PROMPT_FILE

        if not prompt_path.exists():
            try:
                prompt_path.write_text(DEFAULT_SYSTEM_PROMPT, encoding="utf-8")
                logger.info("[Memory] Seeded System-Prompt.md from default")
            except Exception as exc:
                logger.warning(f"[Memory] Could not seed System-Prompt.md: {exc}")
            return DEFAULT_SYSTEM_PROMPT

        try:
            content = prompt_path.read_text(encoding="utf-8")
            logger.info(f"[Memory] Loaded System-Prompt.md ({len(content)} chars)")
            return content
        except Exception as exc:
            logger.warning(f"[Memory] Could not read System-Prompt.md: {exc} — using default")
            return DEFAULT_SYSTEM_PROMPT

    # ------------------------------------------------------------------
    # Context for system prompt injection
    # ------------------------------------------------------------------

    def load_context(self, project: str | None = None) -> str:
        """
        Read memory files and return a string injected after the system prompt.
        Called once at session start.
        """
        parts: list[str] = ["## Persistent Memory\n"]

        profile = self._read_file(self.PROFILE_FILE)
        if profile:
            parts.append("### User Profile\n" + profile)

        facts = self._read_file(self.FACTS_FILE)
        if facts and facts.strip() not in ("", "# Learned Facts"):
            parts.append("### Learned Facts\n" + facts)

        if project:
            project_content = self._read_file(f"{self.PROJECTS_DIR}/{project}.md")
            if project_content:
                parts.append(f"### Project Memory: {project}\n" + project_content)

        context = "\n\n".join(parts)
        logger.info(f"[Memory] Context loaded — {len(context)} chars, project='{project or 'none'}'")
        return context

    # ------------------------------------------------------------------
    # Episode — crash-safe live writing
    # ------------------------------------------------------------------

    def open_episode(self) -> None:
        date_str  = datetime.now().strftime("%Y-%m-%d")
        time_str  = datetime.now().strftime("%H:%M")
        filename  = f"{date_str}.md"
        self._ep_path = self._vault / self.EPISODES_DIR / filename

        if self._ep_path.exists():
            header = f"\n---\n\n## Session — {time_str}\n\n"
        else:
            header = (
                f"# Episode — {date_str}\n\n"
                f"## Session — {time_str}\n\n"
            )

        self._write_ep(header)
        logger.info(f"[Memory] Episode opened: {filename}")

    def append_episode(self, line: str) -> None:
        if self._ep_path is None:
            return
        self._write_ep(line + "\n")

    def close_episode(
        self,
        error_summary: str = "",
        tools_used:    list[str] | None = None,
    ) -> None:
        if self._ep_path is None:
            return

        time_str   = datetime.now().strftime("%H:%M")
        tools_line = ", ".join(sorted(set(tools_used))) if tools_used else "none"
        footer     = f"\n**Session ended:** {time_str}  |  **Tools used:** {tools_line}\n"

        if error_summary and error_summary != "No errors recorded this session.":
            footer += f"\n### Provider Errors\n\n```\n{error_summary}\n```\n"

        self._write_ep(footer)
        logger.info(f"[Memory] Episode closed: {self._ep_path.name}")

    def _write_ep(self, text: str) -> None:
        if self._ep_path is None:
            return
        try:
            with open(self._ep_path, "a", encoding="utf-8") as fh:
                fh.write(text)
                fh.flush()
        except Exception as exc:
            logger.error(f"[Memory] Episode write failed: {exc}")

    # ------------------------------------------------------------------
    # remember: command
    # ------------------------------------------------------------------

    def remember(self, fact: str) -> str:
        fact      = fact.strip()
        if not fact:
            return "Nothing to remember — fact was empty."

        facts_path = self._vault / self.FACTS_FILE
        timestamp  = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry      = f"- [{timestamp}] {fact}\n"

        try:
            with open(facts_path, "a", encoding="utf-8") as fh:
                fh.write(entry)
                fh.flush()
            logger.info(f"[Memory] Remembered: {fact[:60]}")
            return f"✓ Remembered: {fact}"
        except Exception as exc:
            logger.error(f"[Memory] Failed to write fact: {exc}")
            return f"✗ Could not save fact: {exc}"

    # ------------------------------------------------------------------
    # Project memory
    # ------------------------------------------------------------------

    def update_project(self, project: str, content: str) -> str:
        project_path = self._vault / self.PROJECTS_DIR / f"{project}.md"
        timestamp    = datetime.now().strftime("%Y-%m-%d %H:%M")

        if not project_path.exists():
            project_path.write_text(f"# Project Memory: {project}\n\n", encoding="utf-8")

        entry = f"\n### Update — {timestamp}\n{content.strip()}\n"
        try:
            with open(project_path, "a", encoding="utf-8") as fh:
                fh.write(entry)
                fh.flush()
            logger.info(f"[Memory] Project '{project}' updated")
            return f"✓ Project memory '{project}' updated."
        except Exception as exc:
            logger.error(f"[Memory] Failed to update project '{project}': {exc}")
            return f"✗ Could not update project memory: {exc}"

    def list_projects(self) -> list[str]:
        return [p.stem for p in (self._vault / self.PROJECTS_DIR).glob("*.md")]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _read_file(self, rel_path: str) -> str:
        full_path = self._vault / rel_path
        if not full_path.exists():
            return ""
        try:
            return full_path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning(f"[Memory] Could not read {rel_path}: {exc}")
            return ""
