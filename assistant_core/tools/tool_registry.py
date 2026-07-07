"""
Tool Registry — Milestone 4 update
Adds create_note and update_note to the registry.
"""

import logging
from assistant_core.tools.base_tool import BaseTool, ToolResult
from assistant_core.tools.read_note import ReadNoteTool
from assistant_core.tools.search_vault import SearchVaultTool
from assistant_core.tools.list_vault import ListVaultTool
from assistant_core.tools.find_notes import FindNotesTool
from assistant_core.tools.get_linked_notes import GetLinkedNotesTool
from assistant_core.tools.create_note import CreateNoteTool
from assistant_core.tools.update_note import UpdateNoteTool
from assistant_core.tools.file_ops import CopyPathTool, MovePathTool, TrashPathTool, MkdirTool
from assistant_core.tools.research_prompt import ResearchPromptTool
from assistant_core.tools.import_research import ImportResearchTool
from assistant_core.tools.summarise_research import SummariseResearchTool
from assistant_core.tools.provider_tracker import ProviderTrackerTool

logger = logging.getLogger("assistant")


class ToolRegistry:
    """Holds all registered tools and dispatches run() calls by name."""

    def __init__(self, vault_path: str, config: dict | None = None, router=None):
        self._vault_path = vault_path
        self._config     = config or {}
        self._router     = router   # optional — enables a non-agentic title call (M20)
        self._tools: dict[str, BaseTool] = {}
        self._build_tools()

    def _build_tools(self) -> None:
        title_fn = None
        if self._router is not None:
            from assistant_core.research_roundtrip import generate_note_title
            title_fn = lambda content: generate_note_title(self._router, content)

        vault_tools = [
            ReadNoteTool(self._vault_path),
            SearchVaultTool(self._vault_path, self._config),
            ListVaultTool(self._vault_path),
            FindNotesTool(self._vault_path),
            GetLinkedNotesTool(self._vault_path),
            CreateNoteTool(self._vault_path, self._config),
            UpdateNoteTool(self._vault_path, self._config),
            CopyPathTool(self._vault_path),
            MovePathTool(self._vault_path),
            TrashPathTool(self._vault_path),
            MkdirTool(self._vault_path),
            ResearchPromptTool(self._vault_path),
            ImportResearchTool(self._vault_path, title_fn=title_fn),
            SummariseResearchTool(self._vault_path),
            ProviderTrackerTool(self._vault_path, self._config),
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
