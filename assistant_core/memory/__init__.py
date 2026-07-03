"""Memory package — persistent vault-backed memory and conversation context.

`memory_manager.MemoryManager` reads/writes the Markdown memory files under
`AI/Memory/` and `AI/System/`; `context_manager.ContextManager` trims history
to each provider's token budget.
"""
