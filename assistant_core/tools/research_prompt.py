"""
Tool: generate_research_prompt
Generates an optimised prompt for web-based AI systems.

Input: A user question or research topic

The tool will:
    - Take the user's question
    - Access context from the conversation history (if available)
    - Produce a detailed, well-structured prompt optimised for web AI systems
    - Return the prompt text ready to paste into ChatGPT, Gemini, or other services
"""

import logging
from pathlib import Path

from assistant_core.tools.base_tool import BaseTool, ToolResult

logger = logging.getLogger("assistant")


class ResearchPromptTool(BaseTool):
    """Generates an optimised research prompt for external web AI services."""

    def __init__(self, vault_path: str):
        self._vault = Path(vault_path)

    @property
    def name(self) -> str:
        return "generate_research_prompt"

    @property
    def description(self) -> str:
        return "Generate an optimised research prompt to paste into web AI (ChatGPT, Gemini, etc)."

    def run(self, input_data: str) -> ToolResult:
        question = input_data.strip()
        if not question:
            return ToolResult(
                success=False,
                output="No question provided. Usage: vault:research <your question>"
            )

        # Build a well-structured prompt for external AI
        optimised_prompt = self._build_prompt(question)

        logger.info(f"[generate_research_prompt] Generated prompt for: {question[:60]}")
        return ToolResult(
            success=True,
            output=optimised_prompt,
            metadata={"question": question, "prompt_length": len(optimised_prompt)},
        )

    def _build_prompt(self, question: str) -> str:
        """
        Build a structured prompt for web-based AI systems.
        Includes context-setting, specificity guidance, and output formatting.
        """
        prompt = f"""I need help researching the following question for a knowledge management system:

**Question:** {question}

Please provide:
1. **Key facts and principles** — the core facts relevant to this question
2. **Sources or context** — where this information is typically found
3. **Practical applications** — how this knowledge can be used
4. **Related concepts** — ideas related to the main topic
5. **Uncertainties or debates** — areas where experts disagree
6. **Recommended further reading** — books, articles, or resources to explore

Format your response with clear headings and bullet points so it's easy to parse and save to a knowledge base.

Focus on accuracy and depth. Cite sources when possible. If you're unsure about something, say so explicitly."""

        return prompt
