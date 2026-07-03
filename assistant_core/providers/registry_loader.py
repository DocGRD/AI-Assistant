"""
Registry Loader — Milestone 10
===============================
Parses AI/System/Provider-Registry.md into the existing ModelSpec type so the
router can build one generic OpenAI-compatible provider per active row.

- load() : parse every Markdown table whose header carries the registry schema
           (provider_key / base_url / model_id / status). A malformed row is
           SKIPPED and reported — never fatal. A missing file returns [].
- seed() : write the default registry file if it does not yet exist.

The 4-column "Deprecated / Removed" table is ignored automatically because its
header does not contain the registry schema columns.
"""

import logging
import re
from pathlib import Path

from assistant_core.providers.model_registry import ModelSpec

logger = logging.getLogger("assistant")

# Unknown limits are marked "?" in the registry and treated as "no known limit".
NO_KNOWN_LIMIT = 999_999_999

# Columns that identify a row-schema table (vs. the deprecated table or prose).
_REQUIRED_HEADERS = {"provider_key", "base_url", "model_id", "status"}

# Which registry column feeds which ModelSpec field. Integer fields are parsed
# through _parse_limit (so "?" becomes NO_KNOWN_LIMIT).
_INT_COLUMNS = {
    "context_window": "context_window",
    "tpm":            "tpm_limit",
    "rpm":            "rpm_limit",
    "rpd":            "rpd_limit",
    "tpd":            "tpd_limit",
}


# The canonical seed written to the vault on first run. Kept in sync with
# Docs/Provider-Registry.md. Contains NO API keys — keys live in settings.json.
SEED_CONTENT = """# Provider Registry

*Last updated: 2026-06-25*
*Update this file by running: `vault:update-providers`*

This file is the single source of truth for every free-tier endpoint the router can use.
The router reads it at startup. Each **active** row becomes a live provider via the generic
OpenAI-compatible adapter — no Python file per provider. To add a provider, add a row.

The Obsidian plugin's **provider dropdown** is also populated from this list (via the service's
`/status` endpoint), so a new **active** row appears there automatically — no plugin edit needed.

## How the columns are used

- `provider_key` — unique key. The API key is read from settings as `<provider_key>_api_key`.
- `base_url` — OpenAI-compatible base URL. The adapter posts to `<base_url>/chat/completions`.
- `model_id` — exact model string passed in the request.
- `context_window` / `tpm` / `rpm` / `rpd` / `tpd` — limits used for routing and trimming.
  Unknown values are marked `?` and treated as "no known limit" by the router.
- `trains_on_data` — `no` | `yes` | `logs` | `varies`. **Notes flagged `private` route only to `no`.**
- `status` — `active` (router uses it) | `candidate` (registered but NOT routed until tested) | `deprecated`.
- `strengths` — task tags the router matches against (e.g. `reasoning`, `long-context`, `fast`, `volume`).

> **Caveat:** Free tiers change without notice and vary by region/account. These figures are
> current best estimates as of the date above. The authoritative numbers are in each provider's
> console. `vault:update-providers` exists precisely because this table goes stale.

## Active Providers

| provider_key | base_url | model_id | context_window | tpm | rpm | rpd | tpd | trains_on_data | status | strengths | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| google | https://generativelanguage.googleapis.com/v1beta/openai/ | gemini-2.5-flash | 1000000 | 250000 | 15 | 1500 | ? | yes | active | default, long-context, multimodal | **Trains on free-tier prompts — never receives `private` notes.** Pro removed from free tier (Apr 2026); 2.0 retired (Jun 2026) |
| groq | https://api.groq.com/openai/v1 | llama-3.3-70b-versatile | 128000 | 12000 | 30 | 1000 | 100000 | no | active | reasoning, tool-use, fast | RPD cut from 14400 to ~1000 in 2026; good quality but tight daily cap |
| groq | https://api.groq.com/openai/v1 | llama-3.1-8b-instant | 131072 | 6000 | 30 | 14400 | 500000 | no | active | high-volume, fast, cheap fallback | most permissive RPD on Groq free tier |
| cerebras | https://api.cerebras.ai/v1 | gpt-oss-120b | 65536 | 30000 | 5 | 2400 | 1000000 | no | active | volume, batch, fast, reasoning | Free tier (Production): GPT-OSS 120B. 5 RPM / 2,400 RPD / 30K TPM / ~1M tokens/day; very high TPS |

## Candidate Providers (registered, not routed until tested)

| provider_key | base_url | model_id | context_window | tpm | rpm | rpd | tpd | trains_on_data | status | strengths | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| nvidia | https://integrate.api.nvidia.com/v1 | nvidia/llama-3.3-70b-instruct | 128000 | 40000 | 40 | ? | ? | logs | candidate | breadth (100+ models) | Verify credit policy in console — old 1000-credit cap may be lifted to pure 40 RPM. Can request 200 RPM |
| openrouter | https://openrouter.ai/api/v1 | meta-llama/llama-3.3-70b-instruct:free | 128000 | ? | 20 | 200 | ? | varies | candidate | breadth, built-in fallback | One key to many `:free` models. RPD rises to 1000 with $10+ balance |
| cerebras | https://api.cerebras.ai/v1 | zai-glm-4.7 | 64000 | 30000 | 5 | 2400 | 1000000 | no | candidate | preview, reasoning | Cerebras Preview model — same free limits as gpt-oss-120b. Change status to active to route to it |

## Deprecated / Removed

| provider_key | model_id | removed_date | reason |
|---|---|---|---|
| groq | mixtral-8x7b-32768 | 2026-03-01 | Deprecated by Groq |
| google | gemini-2.0-flash | 2026-06-01 | Retired by Google |

## Routing intent (read by the router)

- **Default (non-private):** `google / gemini-2.5-flash` — highest daily budget + 1M context.
- **Default (private notes):** `groq / llama-3.3-70b-versatile`, then `cerebras` — both `trains_on_data = no`.
- **High volume / batch / large notes:** `cerebras`, then `groq / llama-3.1-8b-instant`.
- **Speed-critical short turns:** `groq / llama-3.1-8b-instant`.
- **Floor:** keep at least 3 `active` providers healthy at all times. If a provider fails on live
  traffic, the loader flags it in the startup report and the router stops routing to it until it recovers.
"""


def _parse_limit(value: str) -> int:
    """Map a limit cell to an int. '?' or '' means 'no known limit'."""
    value = (value or "").strip()
    if value in ("?", ""):
        return NO_KNOWN_LIMIT
    return int(value.replace(",", ""))  # raises ValueError on garbage → row skipped


def _split_row(line: str) -> list[str]:
    """Split a Markdown table row into stripped cells (drop leading/trailing pipes)."""
    cells = line.split("|")
    # A line "| a | b |" splits to ['', ' a ', ' b ', ''] — drop the empty ends.
    if cells and cells[0].strip() == "":
        cells = cells[1:]
    if cells and cells[-1].strip() == "":
        cells = cells[:-1]
    return [c.strip() for c in cells]


def _is_separator(cells: list[str]) -> bool:
    """True for the |---|---| separator row beneath a header."""
    return all(set(c) <= {"-", ":"} and c for c in cells) if cells else False


class RegistryLoader:
    """Loads and seeds AI/System/Provider-Registry.md."""

    def __init__(self, registry_path: Path, seed_content: str = SEED_CONTENT):
        self.registry_path = Path(registry_path)
        self.seed_content  = seed_content
        self.skipped: list[str] = []   # human-readable reasons for skipped rows
        self.last_updated: str = "unknown"   # parsed from "*Last updated: <date>*"

    def seed(self) -> None:
        """Write the default registry file if it is missing. Never fatal."""
        if self.registry_path.exists():
            return
        try:
            self.registry_path.parent.mkdir(parents=True, exist_ok=True)
            self.registry_path.write_text(self.seed_content, encoding="utf-8")
            logger.info(f"[RegistryLoader] Seeded provider registry at {self.registry_path}")
        except Exception as exc:
            logger.warning(f"[RegistryLoader] Could not seed registry file: {exc}")

    def load(self) -> list[ModelSpec]:
        """
        Parse the registry file into ModelSpecs. Missing file → []. A malformed
        row is skipped and recorded in self.skipped — never raises.
        """
        self.skipped = []

        if not self.registry_path.exists():
            logger.info(f"[RegistryLoader] No registry file at {self.registry_path} — using fallbacks")
            return []

        try:
            text = self.registry_path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning(f"[RegistryLoader] Could not read registry file: {exc}")
            return []

        # Capture the "*Last updated: <date>*" line for the startup report.
        m = re.search(r"\*\s*Last updated:\s*([^*\n]+?)\s*\*", text, re.IGNORECASE)
        if m:
            self.last_updated = m.group(1).strip()

        specs: list[ModelSpec] = []
        header: list[str] | None = None  # active header → currently inside a schema table

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line.startswith("|"):
                header = None          # any non-table line ends the current table
                continue

            cells = _split_row(line)

            if header is None:
                # Looking for a header row that carries the registry schema.
                if _REQUIRED_HEADERS.issubset(set(cells)):
                    header = cells
                continue

            if _is_separator(cells):
                continue               # the |---| row under the header

            spec = self._row_to_spec(header, cells, line)
            if spec is not None:
                specs.append(spec)

        if self.skipped:
            logger.warning(
                f"[RegistryLoader] Skipped {len(self.skipped)} malformed row(s): "
                + "; ".join(self.skipped)
            )
        logger.info(f"[RegistryLoader] Loaded {len(specs)} provider row(s) from {self.registry_path}")
        return specs

    def _row_to_spec(self, header: list[str], cells: list[str], raw: str) -> ModelSpec | None:
        """Convert one data row into a ModelSpec, or record a skip and return None."""
        if len(cells) != len(header):
            self.skipped.append(f"column count {len(cells)}≠{len(header)} ({raw[:60]})")
            return None

        row = dict(zip(header, cells))
        try:
            int_fields = {field: _parse_limit(row[col]) for col, field in _INT_COLUMNS.items()}
            strengths = [s.strip() for s in row.get("strengths", "").split(",") if s.strip()]
            return ModelSpec(
                provider       = row["provider_key"],
                model_id       = row["model_id"],
                strengths      = strengths,
                weaknesses     = [],
                notes          = row.get("notes", ""),
                base_url       = row.get("base_url", ""),
                status         = row.get("status", "active"),
                trains_on_data = row.get("trains_on_data", ""),
                **int_fields,
            )
        except (ValueError, KeyError) as exc:
            self.skipped.append(f"{row.get('provider_key', '?')}/{row.get('model_id', '?')}: {exc}")
            return None
