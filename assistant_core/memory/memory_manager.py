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
import re
from datetime import datetime
from pathlib import Path

# v1.7 — packaged AI/Help knowledge base. Bump when the seed/help/*.md content changes so
# seed_help() refreshes the vault copies (which carry a matching `<!-- help-version: N -->`).
HELP_VERSION = 43
_HELP_STAMP = re.compile(r"help-version:\s*(\d+)")

# v1.9 — the System-Prompt is now packaged + version-stamped (assistant_core/seed/system/
# System-Prompt.md, carrying `<!-- prompt-version: N -->`). seed_system_prompt() refreshes the
# vault copy when it's missing or older, so the command list never drifts. Bump on prompt edits.
PROMPT_VERSION = 12
_PROMPT_STAMP = re.compile(r"prompt-version:\s*(\d+)")

logger = logging.getLogger("assistant")


def _packaged_system_prompt() -> str | None:
    """Read the canonical packaged System-Prompt (seed/system/System-Prompt.md), or None."""
    try:
        p = Path(__file__).resolve().parents[1] / "seed" / "system" / "System-Prompt.md"
        return p.read_text(encoding="utf-8") if p.is_file() else None
    except Exception:
        return None

# ---------------------------------------------------------------------------
# Default system prompt — written to vault on first run if missing.
# Kept here as the authoritative source-of-truth fallback.
# Edit AI/System/System-Prompt.md in Obsidian to customise.
# ---------------------------------------------------------------------------

DEFAULT_SYSTEM_PROMPT = """You are Loremaster, an AI assistant integrated with an Obsidian vault, with direct tool access.

## Honesty — never fabricate (most important rule)
Only state things you can verify from a tool result present in this conversation. Never claim a vault: command ran, that a file changed, or what a note contains unless you SEE its result (a line starting with the failure mark means it FAILED). Do not invent note contents, paths, quotes, citations, dates, numbers, or command output. If you can't verify something, say "I don't know" or "I can't verify that without running X" — a truthful "I'm not sure" always beats a confident guess. For any arithmetic, use vault:calc.

## Core tools
Put a `vault:` command on its own line and the system runs it, returning the result for your next reply:
vault:read <note> - vault:search <query> - vault:list [folder] - vault:create <path> (full path on the first line, content after) - vault:update <path> - vault:ask <question>.

(This is a minimal safety fallback. The full, current system prompt ships packaged in seed/system/System-Prompt.md and is what normally loads; this text is used only if that file cannot be read.)"""


class MemoryManager:
    """Reads and writes the vault's AI/Memory/ folder."""

    MEMORY_ROOT        = "AI/Memory"
    PROFILE_FILE       = "AI/Memory/User-Profile.md"
    FACTS_FILE         = "AI/Memory/Facts/Learned-Facts.md"
    PROJECTS_DIR       = "AI/Memory/Projects"
    EPISODES_DIR       = "AI/Memory/Episodes"
    SYSTEM_DIR         = "AI/System"
    SYSTEM_PROMPT_FILE = "AI/System/System-Prompt.md"
    WEBUI_PROMPT_FILE = "AI/System/WebUI-Prompt.md"
    PROMPTS_DIR        = "AI/Prompts"

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

    def seed_system_prompt(self, force: bool = False) -> bool:
        """v1.9 — refresh AI/System/System-Prompt.md from the packaged, version-stamped canonical
        prompt when it's missing or its `prompt-version` is older than PROMPT_VERSION (or `force`).
        Keeps the command list current without drifting. A pre-existing prompt is backed up to
        `System-Prompt.bak-<stamp>.md` before it's overwritten, so a customised prompt is never lost.
        Returns True if it wrote. Never raises."""
        packaged = _packaged_system_prompt()
        if not packaged:
            return False
        dest = self._vault / self.SYSTEM_PROMPT_FILE
        try:
            cur = -1
            if dest.exists():
                m = _PROMPT_STAMP.search(dest.read_text(encoding="utf-8"))
                cur = int(m.group(1)) if m else 0
            if not (force or cur < PROMPT_VERSION):
                return False
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                try:
                    bak = dest.with_name(f"System-Prompt.bak-v{cur if cur >= 0 else 0}.md")
                    bak.write_text(dest.read_text(encoding="utf-8"), encoding="utf-8")
                except Exception:
                    pass
            dest.write_text(packaged, encoding="utf-8")
            logger.info(f"[Memory] Seeded/updated System-Prompt.md → prompt-version {PROMPT_VERSION}")
            return True
        except Exception as exc:
            logger.warning(f"[Memory] Could not seed System-Prompt.md: {exc}")
            return False

    def load_system_prompt(self) -> str:
        """
        Read the system prompt from AI/System/System-Prompt.md, refreshing it first from the
        packaged canonical prompt when missing/out-of-date (see seed_system_prompt), so the
        command list the model sees never drifts. Falls back to DEFAULT_SYSTEM_PROMPT.

        Returns the raw prompt string (no memory context appended —
        the caller does that via build_system_prompt()).
        """
        prompt_path = self._vault / self.SYSTEM_PROMPT_FILE

        # Keep the vault copy current (writes only when missing or older than PROMPT_VERSION).
        self.seed_system_prompt()

        if not prompt_path.exists():
            # No packaged prompt available either — fall back to the in-code default.
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

    def seed_webui_prompt(self) -> None:
        """
        Write the default WebUI-Prompt.md to the vault if it doesn't
        exist. Called once at startup so the user can find and edit it
        in Obsidian. The file is the partner instructions sent to web
        AIs during handoff — no vault command syntax should be in it.
        """
        prompt_path = self._vault / self.WEBUI_PROMPT_FILE
        if prompt_path.exists():
            return

        default_content = '''# AI Assistant — Web AI Partner Prompt

*This file is loaded by the assistant when packaging a conversation for a web AI.*
*Edit this file in Obsidian to change how web AI partners behave.*
*Do NOT add vault: command instructions — web AIs cannot execute them.*
*Privacy: turns the user marks `private` are NOT routed here unless they explicitly opt in — assume any context you receive was cleared for web use.*

---

You are a research and thinking partner continuing an AI assistant session on behalf of a user.

The user has a local knowledge management system (Obsidian vault) that you cannot access directly. They will provide relevant context when available. Your job is to think, reason, and answer using the context provided plus your own knowledge.

## How to respond

Answer the question directly and clearly. Be specific, not generic.

If your answer would be significantly improved by information likely in the user\\'s personal notes, say so explicitly at the end — for example:

> "Note: this answer would be more specific if you searched your vault for [topic]."

Do not emit commands. Just note what information would help, in plain English.

## Honesty — do not fabricate

You cannot see the user's vault. Never invent the contents of their notes, files, projects, dates, quotes, or citations — answer only from the context they actually pasted plus your general knowledge, and keep those clearly separated. If the needed information isn't in the provided context and you're unsure, say so plainly rather than guessing. You have no tools here, so never claim to have searched, read, run, or verified anything.

## What you know about the user

The USER CONTEXT section of this prompt contains information about the user, their projects, and their preferences. Use this to personalise your answers.

## Format

Use clear headings and bullet points when the answer is complex. Keep responses concise. Avoid unnecessary preamble.

## Tone

Practical and direct. This user is technically capable and values precision.
'''
        try:
            prompt_path.write_text(default_content, encoding="utf-8")
            logger.info("[Memory] Seeded WebUI-Prompt.md")
        except Exception as exc:
            logger.warning(f"[Memory] Could not seed WebUI-Prompt.md: {exc}")


    def seed_prompts(self) -> None:
        """
        Write a few example reusable prompts to AI/Prompts/ if the folder is empty.
        The plugin's prompt picker lists these; `{{selection}}` / `{{note}}` /
        `{{input}}` are substituted before sending. Edit/add files in Obsidian.
        """
        d = self._vault / "AI" / "Prompts"
        try:
            d.mkdir(parents=True, exist_ok=True)
            if any(d.glob("*.md")):
                return
            examples = {
                "summarize.md":
                    "---\nname: Summarize\n---\n"
                    "Summarize the following concisely, keeping the key points and any decisions:\n\n{{selection}}",
                "improve-writing.md":
                    "---\nname: Improve writing\n---\n"
                    "Rewrite the following to be clearer and better organised, preserving meaning and tone:\n\n{{selection}}",
                "action-items.md":
                    "---\nname: Extract action items\n---\n"
                    "List the concrete action items and open questions in this note as a checklist:\n\n{{note}}",
                "explain.md":
                    "---\nname: Explain simply\n---\n"
                    "Explain the following in plain language, as if to a smart beginner:\n\n{{selection}}",
            }
            for fn, body in examples.items():
                (d / fn).write_text(body, encoding="utf-8")
            logger.info("[Memory] Seeded AI/Prompts/ examples")
        except Exception as exc:
            logger.warning(f"[Memory] Could not seed prompts: {exc}")

    def seed_help(self, force: bool = False) -> list[str]:
        """Write/refresh the indexed AI/Help/ knowledge base from the packaged canonical set
        (assistant_core/seed/help/). A file is (re)written when it's missing or its
        `help-version` marker is older than HELP_VERSION (or `force`) — so Help auto-updates on
        deploy but never clobbers a note unless the packaged version advanced. Returns rel paths."""
        src = Path(__file__).resolve().parents[1] / "seed" / "help"
        if not src.is_dir():
            return []
        dest_dir = self._vault / "AI" / "Help"
        written: list[str] = []
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            for f in sorted(src.glob("*.md")):
                dest = dest_dir / f.name
                cur = -1
                if dest.exists():
                    m = _HELP_STAMP.search(dest.read_text(encoding="utf-8"))
                    cur = int(m.group(1)) if m else 0
                if force or cur < HELP_VERSION:
                    dest.write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
                    written.append(f"AI/Help/{f.name}")
            if written:
                logger.info(f"[Memory] Seeded/updated {len(written)} AI/Help note(s) → v{HELP_VERSION}")
        except Exception as exc:
            logger.warning(f"[Memory] Could not seed help: {exc}")
        return written

    def seed_scripts(self) -> None:
        """Create AI/Scripts/ (+ proposed/) with a README explaining the propose/commit flow."""
        d = self._vault / "AI" / "Scripts"
        try:
            (d / "proposed").mkdir(parents=True, exist_ok=True)
            readme = d / "README.md"
            if readme.exists():
                return
            readme.write_text(
                "# Local Scripts (Muscle Memory)\n\n"
                "Reusable zero-API automation. **Propose/commit:**\n\n"
                "1. The assistant only ever *proposes* a script — it writes it to "
                "`AI/Scripts/proposed/`. It can never run anything itself.\n"
                "2. **Review** the proposed script. To **approve** it, move it from `proposed/` up "
                "into `AI/Scripts/`.\n"
                "3. Run an approved script with `vault:run-script <name>` (no extension). Only `.py` "
                "files directly in `AI/Scripts/` can run; they execute with no arguments and a timeout.\n",
                encoding="utf-8",
            )
            logger.info("[Memory] Seeded AI/Scripts/ README")
        except Exception as exc:
            logger.warning(f"[Memory] Could not seed scripts dir: {exc}")

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
        # Normalize exotic Unicode (narrow-nbsp, nbsp, non-breaking hyphen, zero-width) that models
        # emit — episodes feed consolidation, and those chars break link-matching / fact de-dup.
        from assistant_core.textnorm import normalize_exotic
        text = normalize_exotic(text)
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
