"""
Memory Manager — Milestone 4B (crash-safe episode writing)
===========================================================
Persistent memory stored as plain Markdown inside the Obsidian vault.
All memory is human-readable, searchable, and editable directly in Obsidian.

Memory layout inside the vault (under AI/Memory/):
    User-Profile.md          — static user facts, loaded every session
    Projects/<name>.md       — per-project accumulated knowledge
    Episodes/YYYY-MM-DD.md   — one note per day, written live during the session
    Facts/Learned-Facts.md   — things explicitly told to the assistant

Episode writing strategy (crash-safe):
    open_episode()    — called at startup; creates the file and writes the header
    append_episode()  — called after every event; flushes immediately to disk
    close_episode()   — called at clean shutdown; writes error summary footer
    If the process crashes between open and close, everything up to the last
    append_episode() call is already safely on disk.
"""

import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("assistant")


class MemoryManager:
    """Reads and writes the vault's AI/Memory/ folder."""

    # Paths relative to vault root
    MEMORY_ROOT  = "AI/Memory"
    PROFILE_FILE = "AI/Memory/User-Profile.md"
    FACTS_FILE   = "AI/Memory/Facts/Learned-Facts.md"
    PROJECTS_DIR = "AI/Memory/Projects"
    EPISODES_DIR = "AI/Memory/Episodes"
    SYSTEM_DIR   = "AI/System"

    def __init__(self, vault_path: str):
        self._vault    = Path(vault_path)
        self._ep_path: Path | None = None   # set by open_episode()
        self._ensure_structure()

    # ------------------------------------------------------------------
    # Startup: folder structure and seed files
    # ------------------------------------------------------------------

    def _ensure_structure(self) -> None:
        """Create the AI/Memory/ folder tree if it doesn't exist yet."""
        for d in [
            self._vault / "AI" / "Memory" / "Facts",
            self._vault / "AI" / "Memory" / "Projects",
            self._vault / "AI" / "Memory" / "Episodes",
            self._vault / "AI" / "System",
        ]:
            d.mkdir(parents=True, exist_ok=True)

        self._seed_profile()
        self._seed_facts()

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
    # Startup: load context for system prompt injection
    # ------------------------------------------------------------------

    def load_context(self, project: str | None = None) -> str:
        """
        Read memory files and return a string injected into the system prompt.
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
        """
        Create the episode file for today and write the session header.
        Called once at startup, before the chat loop begins.
        If the file already exists (earlier session today), appends a new
        session divider so the day's file stays cohesive.
        """
        date_str  = datetime.now().strftime("%Y-%m-%d")
        time_str  = datetime.now().strftime("%H:%M")
        filename  = f"{date_str}.md"
        self._ep_path = self._vault / self.EPISODES_DIR / filename

        if self._ep_path.exists():
            # Second or later session today — add a divider
            header = f"\n---\n\n## Session — {time_str}\n\n"
        else:
            # First session today — create the file with a heading
            header = (
                f"# Episode — {date_str}\n\n"
                f"## Session — {time_str}\n\n"
            )

        self._write_ep(header)
        logger.info(f"[Memory] Episode opened: {filename}")

    def append_episode(self, line: str) -> None:
        """
        Append one line (or block) to the episode file immediately.
        Called after every user action — vault commands, chat, remember, errors.
        Each call flushes to disk so a crash loses nothing already appended.
        """
        if self._ep_path is None:
            return   # open_episode() wasn't called — silently skip
        self._write_ep(line + "\n")

    def close_episode(self, error_summary: str = "", tools_used: list[str] | None = None) -> None:
        """
        Write the session footer at clean shutdown.
        Called from assistant.py on exit (or Ctrl+C).
        If the process was killed before this runs, the episode still has
        everything up to the last append_episode() call.
        """
        if self._ep_path is None:
            return

        time_str   = datetime.now().strftime("%H:%M")
        tools_line = ", ".join(sorted(set(tools_used))) if tools_used else "none"

        footer = f"\n**Session ended:** {time_str}  |  **Tools used:** {tools_line}\n"

        if error_summary and error_summary != "No errors recorded this session.":
            footer += f"\n### Provider Errors\n\n```\n{error_summary}\n```\n"

        self._write_ep(footer)
        logger.info(f"[Memory] Episode closed: {self._ep_path.name}")

    def _write_ep(self, text: str) -> None:
        """Append text to the episode file and flush immediately."""
        if self._ep_path is None:
            return
        try:
            with open(self._ep_path, "a", encoding="utf-8") as fh:
                fh.write(text)
                fh.flush()   # ensure OS writes to disk, not just to buffer
        except Exception as exc:
            logger.error(f"[Memory] Episode write failed: {exc}")

    # ------------------------------------------------------------------
    # During session: remember a fact
    # ------------------------------------------------------------------

    def remember(self, fact: str) -> str:
        """Append a fact to Learned-Facts.md immediately."""
        fact = fact.strip()
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
        """Create or append to a project memory note."""
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
