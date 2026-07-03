"""
Content Chunking Utility — Split large notes for processing.

Chunks notes by sections (headings) when possible, or by word count.
Keeps chunks under a specified token budget.
"""

import logging
from assistant_core.providers.model_registry import estimate_tokens

logger = logging.getLogger("watcher")


class ContentChunker:
    """Split large content into processable chunks."""

    def __init__(self, max_tokens: int = 4000):
        """
        Initialize chunker.

        Args:
            max_tokens: Maximum tokens per chunk (reserve ~2000 for response)
        """
        self.max_tokens = max_tokens

    def chunk_content(self, content: str) -> list[str]:
        """
        Split content into chunks that fit within token budget.

        Strategy:
        1. Try to split by heading (## Section)
        2. If a section is still too large, split by word count
        3. Return list of chunks

        Args:
            content: The note content to chunk

        Returns:
            List of content chunks (each under max_tokens)
        """
        token_count = estimate_tokens([], content)
        
        # If content fits in one chunk, return as-is
        if token_count <= self.max_tokens:
            return [content]

        logger.info(f"[ContentChunker] Content too large ({token_count} tokens), chunking...")

        chunks = []
        
        # First try: split by markdown headings (##, ###, etc)
        sections = self._split_by_heading(content)
        
        if len(sections) > 1:
            logger.info(f"[ContentChunker] Split into {len(sections)} sections by heading")
        
        # Second pass: if any section is still too large, split it further
        for section in sections:
            section_tokens = estimate_tokens([], section)
            if section_tokens <= self.max_tokens:
                chunks.append(section)
            else:
                logger.info(f"[ContentChunker] Section still too large ({section_tokens} tokens), splitting by word count")
                sub_chunks = self._split_by_word_count(section, self.max_tokens)
                chunks.extend(sub_chunks)
        
        logger.info(f"[ContentChunker] Final: {len(chunks)} chunks")
        return chunks

    def _split_by_heading(self, content: str) -> list[str]:
        """Split content by markdown headings (## level 2+)."""
        sections = []
        current_section = []
        
        for line in content.splitlines(keepends=True):
            # Check if line is a heading (## or ###, etc — not #)
            if line.startswith("##") and not line.startswith("#####"):
                # Save previous section if not empty
                if current_section:
                    sections.append("".join(current_section))
                # Start new section
                current_section = [line]
            else:
                current_section.append(line)
        
        # Add last section
        if current_section:
            sections.append("".join(current_section))
        
        return sections if len(sections) > 1 else [content]

    def _split_by_word_count(self, content: str, max_tokens: int) -> list[str]:
        """
        Split content by approximating word count to tokens.
        Rough estimate: 1 token ≈ 4 characters or 0.75 words.
        """
        words = content.split()
        max_words = max(int(max_tokens * 0.75), 100)  # At least 100 words per chunk
        
        chunks = []
        current_chunk = []
        current_tokens = 0
        
        for word in words:
            word_tokens = estimate_tokens([], word)
            
            if current_tokens + word_tokens > max_tokens and current_chunk:
                # Save current chunk and start new one
                chunks.append(" ".join(current_chunk))
                current_chunk = [word]
                current_tokens = word_tokens
            else:
                current_chunk.append(word)
                current_tokens += word_tokens
        
        # Add last chunk
        if current_chunk:
            chunks.append(" ".join(current_chunk))
        
        return chunks
