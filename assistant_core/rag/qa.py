"""
Vault QA orchestration — Milestone 11.

Glues retrieval to generation: retrieve top-k chunks, inject them as cited
context, and ask the router for a grounded answer. Shared by the terminal
`vault:ask` command and (later) the HTTP Vault-QA mode.

Privacy: if **any** retrieved source is from a `private` note, the answer is
generated with `private=True` so it routes only to providers that don't train on
data — a private note's content can't leak to a training provider via retrieval.
The web handoff is disabled (QA needs a text answer, not a paste-back).
"""

QA_SYSTEM = (
    "You are answering a question using excerpts from the user's personal Obsidian vault. "
    "Use ONLY the provided sources. If they don't contain the answer, say so plainly — do not "
    "invent facts. Be concise, and cite the source notes you used by their [Source: ...] path."
)


def run_vault_qa(router, retriever, question: str, k: int = 6, force_private: bool = False,
                 max_tokens: int = 2048, temperature: float = 0.3, scope: dict | None = None) -> dict:
    """
    Returns {answer, sources, provider, private, hits}. `answer` is None when the
    index has no relevant notes (caller shows a friendly message). `scope` (optional)
    restricts retrieval to a folder prefix and/or a tag.
    """
    from assistant_core.providers.base_provider import Message

    hits = retriever.retrieve(question, k=k, scope=scope)
    if not hits:
        return {"answer": None, "sources": [], "provider": None, "private": force_private, "hits": []}

    private  = force_private or any(h.private for h in hits)
    context  = retriever.build_context(hits)
    messages = [Message(role="user", content=f"{context}\n\n---\n\nQuestion: {question}")]

    answer, used = router.generate(
        messages, system_prompt=QA_SYSTEM, max_tokens=max_tokens, temperature=temperature,
        private=private, allow_webui=False, task="qa",
    )

    sources: list[str] = []
    source_kinds: list[str] = []          # M16 — "vector" | "graph", aligned with `sources`
    for h in hits:
        c = h.citation()
        if c not in sources:
            sources.append(c)
            source_kinds.append(getattr(h, "source", "vector"))

    return {"answer": answer, "sources": sources, "source_kinds": source_kinds,
            "provider": used, "private": private, "hits": hits}
