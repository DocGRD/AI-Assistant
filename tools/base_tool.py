"""
Base Tool
Every tool the assistant can use must inherit from this class.

Design principle: the assistant never does work directly.
It selects a tool, calls tool.run(input), and gets a result back.
Adding a new capability = write a new subclass. Nothing else changes.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ToolResult:
    """
    The standard return type for every tool.
    success  : True if the tool completed without error
    output   : The string result to show / feed back to the AI
    metadata : Any extra structured data the caller might want
    """
    success: bool
    output: str
    metadata: dict = field(default_factory=dict)


class BaseTool(ABC):
    """Abstract base class for all assistant tools."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier used in logs and tool selection (e.g. 'read_note')."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """One-sentence description of what this tool does."""
        ...

    @abstractmethod
    def run(self, input_data: str) -> ToolResult:
        """
        Execute the tool.

        Args:
            input_data: The tool's primary input as a plain string.
                        Each tool defines what this string means.

        Returns:
            ToolResult with success flag, output text, and optional metadata.
        """
        ...
