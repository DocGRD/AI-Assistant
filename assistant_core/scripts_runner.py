"""
Muscle-memory script runner — Milestone 15 (propose/commit).

The agent only ever *proposes* a reusable script (it writes it to
`AI/Scripts/proposed/` via vault:create — it can never run it). You review it and,
to **approve**, move it into `AI/Scripts/`. Only then can you run it with
`vault:run-script <name>`.

Hard guardrails: the name must be a bare identifier (no slashes/dots → no path
traversal); the target must be a `.py` file directly in `AI/Scripts/`; it runs with
the venv interpreter, no arguments, in the scripts dir, with a timeout.
"""

import re
import subprocess
import sys
from pathlib import Path

_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def run_vault_script(vault_path: str, name: str, timeout: int = 30) -> tuple[bool, str]:
    """Run an approved AI/Scripts/<name>.py. Returns (ok, output)."""
    if not _NAME_RE.match(name or ""):
        return False, "Invalid script name — use letters, digits, '_' or '-' only (no paths)."

    scripts_dir = (Path(vault_path) / "AI" / "Scripts").resolve()
    target = (scripts_dir / f"{name}.py").resolve()

    # Defense in depth: must be a .py directly inside AI/Scripts (never proposed/ or elsewhere).
    if target.parent != scripts_dir or not target.exists():
        return False, (f"No approved script 'AI/Scripts/{name}.py'. "
                       f"Move it out of AI/Scripts/proposed/ to approve it first.")

    try:
        proc = subprocess.run(
            [sys.executable, str(target)],
            cwd=str(scripts_dir), capture_output=True, text=True, timeout=timeout,
        )
        out = ((proc.stdout or "") + (proc.stderr or "")).strip()
        return proc.returncode == 0, out or "(no output)"
    except subprocess.TimeoutExpired:
        return False, f"Script timed out after {timeout}s."
    except Exception as exc:
        return False, f"Run failed: {exc}"
