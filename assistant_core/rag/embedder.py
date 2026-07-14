"""
Local embedder — Milestone 11.

Embeddings run **locally** inside the service (zero cost, fully private — the vault
never leaves the machine). Default model: fastembed `BAAI/bge-small-en-v1.5`
(384-dim, ONNX/CPU, ~130 MB downloaded once, then offline).

The model is loaded lazily on the first `embed()` so importing this module (and
constructing a `LocalEmbedder`) is cheap and never touches the network. Tests
inject a deterministic fake embedder instead, so they never download anything.
"""

import logging
import numpy as np

logger = logging.getLogger("assistant")

EMBED_MODEL = "BAAI/bge-small-en-v1.5"
EMBED_DIM   = 384


def normalize(v: np.ndarray) -> np.ndarray:
    """L2-normalise so a dot product equals cosine similarity."""
    v = np.asarray(v, dtype=np.float32)
    if v.ndim == 1:
        n = float(np.linalg.norm(v)) or 1.0
        return (v / n).astype(np.float32)
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (v / norms).astype(np.float32)


class LocalEmbedder:
    """
    fastembed-backed embedder. Model loads lazily on first use.

    Device + thread count come from settings so the always-on GPU box can run
    `embedding_device: cuda` (needs `fastembed-gpu` / onnxruntime-gpu) while a
    laptop stays on a gentle, thread-capped CPU path (or simply never indexes).
    """

    name = EMBED_MODEL
    dim  = EMBED_DIM

    def __init__(self, config: dict | None = None):
        config = config or {}
        self._config = config
        self.device  = str(config.get("embedding_device", "cpu")).lower()
        self.threads = config.get("embedding_threads")   # int | None (CPU thread cap)
        self._model  = None

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise RuntimeError(
                "The 'fastembed' library is not installed.\nRun: pip install fastembed"
            ) from exc

        kwargs: dict = {}
        if self.device == "cuda":
            # Load CUDA/cuDNN from the `nvidia-*-cu12` pip packages so onnxruntime-gpu
            # finds them WITHOUT a system install or LD_LIBRARY_PATH (works under systemd).
            try:
                import onnxruntime
                if hasattr(onnxruntime, "preload_dlls"):
                    onnxruntime.preload_dlls()
            except Exception as exc:
                logger.debug(f"[RAG] onnxruntime.preload_dlls skipped: {exc}")
            # Cap the CUDA memory arena. Default onnxruntime grabs a huge arena (~3.6 GB for a
            # ~130 MB model), starving anything else on the card (e.g. a co-resident local LLM).
            # kSameAsRequested keeps the footprint minimal; gpu_mem_limit is a hard ceiling.
            mem_mb = int(self._config.get("embedding_gpu_mem_mb", 1024) or 1024)
            kwargs["providers"] = [
                ("CUDAExecutionProvider", {
                    "arena_extend_strategy": "kSameAsRequested",
                    "gpu_mem_limit": mem_mb * 1024 * 1024,
                }),
                "CPUExecutionProvider",
            ]
        if self.threads:
            try:
                kwargs["threads"] = int(self.threads)
            except (TypeError, ValueError):
                pass

        import os

        def _build(kw: dict):
            return TextEmbedding(model_name=EMBED_MODEL, **kw)

        # Offline-first: once the model is cached, load it WITHOUT any network call.
        # huggingface_hub otherwise does a revision check on every load that can hang
        # indefinitely behind a flaky CDN even though the model is present locally
        # (this stalled a live session ~27s). Only if the cached load fails do we go
        # online for the one-time ~130 MB download.
        had_offline = "HF_HUB_OFFLINE" in os.environ
        os.environ["HF_HUB_OFFLINE"] = "1"
        try:
            try:
                self._model = _build(kwargs)
                logger.info(f"[RAG] Embedding model {EMBED_MODEL} loaded from cache ({self.device}).")
                return
            except Exception:
                pass   # not cached yet (or a device issue) → fall through to an online build
            del os.environ["HF_HUB_OFFLINE"]
            logger.info(f"[RAG] Downloading embedding model {EMBED_MODEL} (~130 MB, one time)...")
            try:
                self._model = _build(kwargs)
            except Exception as exc:
                if self.device == "cuda":
                    logger.warning(f"[RAG] CUDA embedding unavailable ({exc}) — falling back to CPU. "
                                   f"Install 'fastembed-gpu' + onnxruntime-gpu on the GPU box.")
                    kwargs.pop("providers", None)
                    self._model = _build(kwargs)
                else:
                    raise
        finally:
            if had_offline:
                os.environ["HF_HUB_OFFLINE"] = "1"
            else:
                os.environ.pop("HF_HUB_OFFLINE", None)

    def embed(self, texts: list[str]) -> np.ndarray:
        """Return an (N, dim) float32 matrix of L2-normalised embeddings."""
        texts = list(texts)
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        self._load()
        try:
            vecs = np.array(list(self._model.embed(texts)), dtype=np.float32)
        except Exception as exc:
            # A CUDA out-of-memory at inference time (e.g. a co-resident local LLM spiked VRAM on
            # a small shared GPU) must NOT crash indexing. Rebuild on CPU once and retry, and stay
            # on CPU for the rest of this process so it self-stabilizes instead of failing every run.
            if self.device == "cuda":
                logger.warning(f"[RAG] CUDA embedding failed ({exc}) — falling back to CPU embedding "
                               f"for this process (the model is tiny; CPU is fine).")
                self.close()
                self.device = "cpu"
                self._load()
                vecs = np.array(list(self._model.embed(texts)), dtype=np.float32)
            else:
                raise
        return normalize(vecs)

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]

    def close(self) -> None:
        """Release the model (and its GPU memory). Call before a restart so the CUDA arena is
        freed cleanly — the in-place `os.execv` restart otherwise leaks VRAM (onnxruntime's
        context isn't torn down), which used to pile up across restarts."""
        if self._model is None:
            return
        try:
            del self._model
        finally:
            self._model = None
        try:
            import gc
            gc.collect()
        except Exception:
            pass


DEFAULT_OLLAMA_EMBED_MODEL = "nomic-embed-text"   # 768-dim, ~274 MB, strong RAG quality


class OllamaEmbedder:
    """Embeds via a local **Ollama** model instead of fastembed/onnxruntime.

    Why: on a small shared GPU, onnxruntime-gpu's cuDNN context is ~2 GB even for a 130 MB
    model, which starves a co-resident Ollama LLM. Ollama's embedding models run on its own
    lightweight GGML runtime (a few hundred MB) and share the GPU with the chat model, so the
    embedder AND the local LLM both fit. Same interface as LocalEmbedder (name/dim/embed/
    embed_one/close) so it drops into RagService unchanged.

    The embedding dimension differs per model (nomic-embed-text = 768 vs bge-small = 384), so
    switching backends changes `name`+`dim`; VectorStore detects that and rebuilds the index.
    """

    def __init__(self, config: dict | None = None):
        import json  # noqa: F401 (kept local so importing the module stays dependency-free)
        config       = config or {}
        self._config = config
        self.model   = str(config.get("ollama_embedding_model") or DEFAULT_OLLAMA_EMBED_MODEL)
        base         = str(config.get("local_base_url") or "http://127.0.0.1:11434/v1").rstrip("/")
        # Use the OpenAI-compatible endpoint (…/v1/embeddings) rather than Ollama's native
        # /api/embed: the native path stalled a full reindex on the box, while the OpenAI path
        # (the same one the cloud providers use) is reliable there.
        self._openai = base if base.endswith("/v1") else base + "/v1"
        self._dim    = None
        self._batch  = int(config.get("ollama_embedding_batch", 16) or 16)

    @property
    def name(self) -> str:
        return f"ollama:{self.model}"

    @property
    def dim(self) -> int:
        if self._dim is None:
            vec = self._embed_raw(["dimension probe"])
            self._dim = len(vec[0]) if vec and vec[0] else 0
            if not self._dim:
                raise RuntimeError(f"Ollama embedding model '{self.model}' returned no vector — "
                                   f"is it pulled? (`ollama pull {self.model}`)")
            logger.info(f"[RAG] Ollama embedder '{self.model}' ready — {self._dim} dims.")
        return self._dim

    def _embed_raw(self, texts: list[str], timeout: int = 60) -> list[list[float]]:
        """Embed a batch via the OpenAI-compatible /v1/embeddings endpoint. Empty/whitespace
        inputs are replaced with a single '.' (an empty string in a batch can stall the embed
        endpoint). Retries once on failure. Returns vectors in the input order."""
        import json, urllib.request
        safe = [(t if (t and t.strip()) else ".") for t in texts]
        body = json.dumps({"model": self.model, "input": safe}).encode("utf-8")
        last: Exception | None = None
        for attempt in range(2):
            try:
                req = urllib.request.Request(f"{self._openai}/embeddings", data=body,
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:   # noqa: S310 (localhost)
                    data = json.loads(resp.read().decode("utf-8"))
                rows = data.get("data") or []
                rows.sort(key=lambda r: r.get("index", 0))   # OpenAI returns index; keep input order
                return [r.get("embedding") for r in rows]
            except Exception as exc:
                last = exc
                logger.warning(f"[RAG] Ollama embed batch failed (attempt {attempt+1}): {exc}")
        raise RuntimeError(f"Ollama embed failed after retry: {last}")

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        out: list[list[float]] = []
        for i in range(0, len(texts), self._batch):     # batch so a huge reindex request never times out
            out.extend(self._embed_raw(texts[i:i + self._batch]))
        vecs = np.array(out, dtype=np.float32)
        return normalize(vecs)

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]

    def close(self) -> None:
        """No-op: Ollama owns the model's GPU memory in its own process; nothing to release here."""
        return
