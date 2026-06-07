"""
Tool Registry — Milestone 4 update
Adds create_note and update_note to the registry.
"""

import logging
from tools.base_tool import BaseTool, ToolResult
from tools.read_note import ReadNoteTool
from tools.search_vault import SearchVaultTool
from tools.list_vault import ListVaultTool
from tools.get_linked_notes import GetLinkedNotesTool
from tools.create_note import CreateNoteTool
from tools.update_note import UpdateNoteTool
from tools.research_prompt import ResearchPromptTool
from tools.import_research import ImportResearchTool
from tools.summarise_research import SummariseResearchTool

logger = logging.getLogger("assistant")


class ToolRegistry:
    """Holds all registered tools and dispatches run() calls by name."""

    def __init__(self, vault_path: str):
        self._vault_path = vault_path
        self._tools: dict[str, BaseTool] = {}
        self._build_tools()

    def _build_tools(self) -> None:
        vault_tools = [
            ReadNoteTool(self._vault_path),
            SearchVaultTool(self._vault_path),
            ListVaultTool(self._vault_path),
            GetLinkedNotesTool(self._vault_path),
            CreateNoteTool(self._vault_path),
            UpdateNoteTool(self._vault_path),
            ResearchPromptTool(self._vault_path),
            ImportResearchTool(self._vault_path),
            SummariseResearchTool(self._vault_path),
        ]
        for tool in vault_tools:
            self._tools[tool.name] = tool
            logger.info(f"[Registry] Registered tool: {tool.name}")

    def run(self, tool_name: str, input_data: str = "") -> ToolResult:
        tool = self._tools.get(tool_name)
        if tool is None:
            available = ", ".join(self._tools.keys())
            return ToolResult(
                success=False,
                output=f"Unknown tool '{tool_name}'. Available: {available}"
            )
        logger.info(f"[Registry] Running tool: {tool_name}")
        try:
            return tool.run(input_data)
        except Exception as exc:
            logger.error(f"[Registry] Tool '{tool_name}' raised: {exc}")
            return ToolResult(success=False, output=f"Tool error: {exc}")

    def list_tools(self) -> list[dict]:
        return [
            {"name": t.name, "description": t.description}
            for t in self._tools.values()
        ]

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())
