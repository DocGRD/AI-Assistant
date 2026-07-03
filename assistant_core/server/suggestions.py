"""Convert plain-English vault-search hints from a web AI into vault: commands.

Web AIs reading WebUI-Prompt.md are told to *suggest* searches in plain English
rather than emit commands. The handoff-return endpoint uses this to turn phrases
like "search your vault for X" into `vault:search X` and run them automatically.
"""

import re

_VAULT_SUGGESTION_PATTERNS = [
    # "search your vault for X" → vault:search X
    (re.compile(
        r"search(?:\s+your)?\s+vault\s+for\s+[\"']?([^\"'\n\.]{3,60})[\"']?",
        re.IGNORECASE),
     "vault:search {0}"),
    # "check your notes on X" → vault:search X
    (re.compile(
        r"check(?:\s+your)?\s+(?:notes?|vault)\s+(?:on|about|for)\s+[\"']?([^\"'\n\.]{3,60})[\"']?",
        re.IGNORECASE),
     "vault:search {0}"),
    # "look in your vault for X" → vault:search X
    (re.compile(
        r"look(?:\s+in)?\s+(?:your\s+)?(?:vault|notes?)\s+(?:for|about)\s+[\"']?([^\"'\n\.]{3,60})[\"']?",
        re.IGNORECASE),
     "vault:search {0}"),
]


def extract_vault_suggestions(text: str) -> list[str]:
    """Return the de-duplicated vault: commands implied by `text`."""
    commands: list[str] = []
    for pattern, template in _VAULT_SUGGESTION_PATTERNS:
        for match in pattern.finditer(text):
            query   = match.group(1).strip().rstrip(".")
            command = template.format(query)
            if command not in commands:
                commands.append(command)
    return commands
