"""
M9 edit helpers — shared by the HTTP edit flow (server.py) and the watcher
staging path (watcher/request_handler.py).

No FastAPI / network dependencies. The model only ever PROPOSES; these helpers
shape the prompt, clean the reply, and (for the Vault path) serialise a proposal
into a marker-delimited block in the note — mirroring provider_tracker's
propose/commit pattern. The plugin is the single commit point.
"""

import json
import re
from datetime import datetime

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

EDIT_SYSTEM = (
    "You are a precise text editor. The user gives an instruction and a region of a note. "
    "Return ONLY the revised text for that region — no preamble, no explanation, no code "
    "fences, no surrounding quotes. Preserve meaning and formatting unless the instruction "
    "says otherwise."
)

EDIT_WORD_SYSTEM = (
    "You are a precise word editor. Given a word or short phrase and an instruction, return up "
    "to 4 alternative replacements, ONE PER LINE — no numbering, no bullets, no quotes, no "
    "preamble, no explanation."
)

# Vault proposal block markers — `apply` (in the plugin) reads what's between them.
BEGIN_MARK = "<!-- AI-EDIT-PROPOSAL"
END_MARK   = "AI-EDIT-PROPOSAL-END -->"
PROPOSAL_HEADING = "## Assistant Proposed Edit"

# M31 — a single edit call is capped at max_tokens, so a large selection's rewrite gets
# truncated. Above this size we split the selection, edit each part, and reassemble.
EDIT_CHUNK_CHARS = 3500


def split_for_edit(text: str, max_chars: int = EDIT_CHUNK_CHARS) -> list[str]:
    """
    Split `text` into ordered chunks each ≤ max_chars, preferring paragraph boundaries
    (blank lines); a single oversized paragraph is hard-split. Returns [text] when it
    already fits. Reassemble edited chunks with "\\n\\n".join(...).
    """
    text = text or ""
    if len(text) <= max_chars:
        return [text]
    units: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        while len(para) > max_chars:
            units.append(para[:max_chars])
            para = para[max_chars:]
        units.append(para)
    chunks: list[str] = []
    cur = ""
    for u in units:
        if not cur:
            cur = u
        elif len(cur) + 2 + len(u) <= max_chars:
            cur += "\n\n" + u
        else:
            chunks.append(cur)
            cur = u
    if cur:
        chunks.append(cur)
    return chunks


# ---------------------------------------------------------------------------
# Reply cleaning
# ---------------------------------------------------------------------------

def clean_edit_reply(reply: str | None) -> str:
    """Strip preamble/code-fence noise so the replacement is just the revised text."""
    if not reply:
        return ""
    text = reply.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2 and lines[-1].strip().startswith("```"):
            text = "\n".join(lines[1:-1]).strip()
    return text


def parse_options(reply: str | None) -> list[str]:
    """Parse a word-edit reply into clean alternatives (one per line), leniently."""
    text = clean_edit_reply(reply)
    opts: list[str] = []
    for line in text.splitlines():
        s = re.sub(r"^(\d+[.)]\s*|[-*•]\s*)", "", line.strip()).strip()
        s = s.strip("\"'").strip()
        if s and s not in opts:
            opts.append(s)
    return opts[:6]


# ---------------------------------------------------------------------------
# Proposal object
# ---------------------------------------------------------------------------

def make_proposal(*, note_path, scope, intent, original_text, replacement,
                  options=None, offsets=None, anchor=None, source, provider=None) -> dict:
    ts = datetime.now()
    return {
        "id":            f"ep-{ts.strftime('%Y%m%d%H%M%S')}",
        "note_path":     note_path,
        "scope":         scope,
        "intent":        intent,
        "original_text": original_text,
        "replacement":   replacement,
        "options":       options or [],
        "offsets":       offsets,      # Live (plugin owns them); None for Vault
        "anchor":        anchor,       # Vault (heading + snippet); None for Live
        "source":        source,       # "live" | "vault"
        "status":        "proposed",
        "created":       ts.isoformat(timespec="seconds"),
        "provider":      provider,
    }


# ---------------------------------------------------------------------------
# Vault anchor + section extraction (the watcher has only the file)
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


def _norm_heading(text: str) -> str:
    """Normalise a heading reference: drop leading #'s and surrounding whitespace."""
    return re.sub(r"^#+\s*", "", (text or "").strip()).strip().lower()


def section_text(body: str, heading: str) -> tuple[str, bool]:
    """
    Return (section_body, found) for the section under `heading`.
    The section body is everything after the matching heading line up to (but not
    including) the next heading of the same or higher level. The heading line itself
    is preserved in the note (only its content is the edit target).
    """
    target = _norm_heading(heading)
    if not target:
        return "", False
    lines = body.splitlines()
    start = None
    level = 0
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m and m.group(2).strip().lower() == target:
            start = i
            level = len(m.group(1))
            break
    if start is None:
        return "", False
    end = len(lines)
    for j in range(start + 1, len(lines)):
        m = _HEADING_RE.match(lines[j])
        if m and len(m.group(1)) <= level:
            end = j
            break
    return "\n".join(lines[start + 1:end]).strip("\n"), True


def make_anchor(heading: str | None, original_text: str, body: str) -> dict:
    """
    Locating info the plugin uses to resolve the region without offsets:
    the heading (if any), a short unique-ish snippet, and which occurrence of that
    snippet in the body this refers to (1-based).
    """
    snippet = " ".join(original_text.split())[:60]
    occurrence = 1
    if snippet:
        # count occurrences of the snippet's leading literal up to the region start
        head = original_text[:60]
        idx = body.find(head)
        if idx > 0:
            occurrence = body.count(head, 0, idx) + 1
    return {
        "heading":    _strip(heading),
        "snippet":    snippet,
        "occurrence": occurrence,
    }


def _strip(v):
    return v.strip() if isinstance(v, str) and v.strip() else None


# ---------------------------------------------------------------------------
# Proposal block (serialise into / extract from a note)
# ---------------------------------------------------------------------------

def render_proposal_block(proposal: dict) -> str:
    """A marker-delimited block appended to the note. Body above it stays untouched."""
    payload = json.dumps(proposal, ensure_ascii=False, indent=2)
    target  = proposal.get("anchor", {}).get("heading") if proposal.get("anchor") else None
    where   = f"`{target}`" if target else "the whole note"
    return (
        f"\n\n{PROPOSAL_HEADING}\n\n"
        f"{BEGIN_MARK}\n{payload}\n{END_MARK}\n\n"
        f"> Proposed replacement for {where}. Open this note in the AI Assistant plugin to "
        f"review and **Replace**, or delete this section to reject.\n"
    )


def extract_proposal(content: str) -> dict | None:
    """Parse the EditProposal JSON out of a note's proposal block, or None."""
    if BEGIN_MARK not in content or END_MARK not in content:
        return None
    seg = content.split(BEGIN_MARK, 1)[1].split(END_MARK, 1)[0].strip()
    try:
        return json.loads(seg)
    except (ValueError, TypeError):
        return None


def strip_proposal_block(content: str) -> str:
    """Remove the proposal section (heading + block + preview) from a note's content."""
    if PROPOSAL_HEADING in content:
        return content.split(PROPOSAL_HEADING, 1)[0].rstrip() + "\n"
    return content
