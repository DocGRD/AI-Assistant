"""
Frontmatter Parser — Parse and update YAML frontmatter in Markdown notes.

YAML frontmatter is the optional YAML block between --- delimiters at the top of a file.

Format:
---
key1: value1
key2: value2
---

Content here...
"""

import logging

logger = logging.getLogger("watcher")


class FrontmatterParser:
    """Parse and update YAML frontmatter in Markdown files."""

    @staticmethod
    def extract(content: str) -> tuple[dict, str]:
        """
        Extract frontmatter and body from Markdown content.

        Returns:
            (frontmatter_dict, body_content)
            If no frontmatter, returns ({}, full_content)
        """
        if not content.startswith("---"):
            return {}, content

        # Find the closing --- delimiter
        lines = content.splitlines(keepends=True)
        closing_idx = None

        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                closing_idx = i
                break

        if closing_idx is None:
            # No closing delimiter found
            return {}, content

        # Parse YAML frontmatter
        fm_lines = lines[1:closing_idx]
        fm_text = "".join(fm_lines).strip()
        body_lines = lines[closing_idx + 1 :]
        body = "".join(body_lines)

        fm_dict = FrontmatterParser._parse_yaml(fm_text)
        return fm_dict, body

    @staticmethod
    def _parse_yaml(yaml_text: str) -> dict:
        """
        Simple YAML key-value parser (no nested structures).
        Handles basic key: value pairs.
        """
        result = {}
        for line in yaml_text.strip().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip().strip('"\'')
        return result

    @staticmethod
    def build(frontmatter: dict, body: str) -> str:
        """
        Build Markdown content with frontmatter and body.

        Returns:
            Complete Markdown content with --- delimiters
        """
        if not frontmatter:
            return body.strip()

        fm_lines = ["---"]
        for key, value in frontmatter.items():
            # Escape quotes in values
            val_str = str(value).replace('"', '\\"')
            fm_lines.append(f'{key}: "{val_str}"')
        fm_lines.append("---")
        fm_lines.append("")

        return "\n".join(fm_lines) + body.lstrip()

    @staticmethod
    def update_field(content: str, field: str, value: str) -> str:
        """
        Update a single field in frontmatter, preserving body.
        If frontmatter doesn't exist, creates it.
        """
        fm_dict, body = FrontmatterParser.extract(content)
        fm_dict[field] = value
        return FrontmatterParser.build(fm_dict, body)
