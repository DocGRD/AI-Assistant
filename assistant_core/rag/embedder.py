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
        vecs = np.array(list(self._model.embed(texts)), dtype=np.float32)
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
