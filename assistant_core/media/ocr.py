"""
Image & handwriting OCR — Milestone 19, Slices 2/3/4/5.

Makes image and handwriting notes answerable in Vault QA. For each image embedded in a
note, extract its text — preferring a **free multimodal model** (good at handwriting),
falling back to local **tesseract** (offline / printed text). The result is written as an
**additive, clearly-AI-derived sidecar** (`AI/Derived/<note>.ocr.md`) that never touches
the original and feeds the M11 index. Privacy carries over: a `private` note's images go
only to no-train multimodal providers or local tesseract (M10 rule).

The vision and tesseract callables are injectable so the whole flow is testable without a
model or the tesseract binary.
"""

from __future__ import annotations

import base64
import logging
import re
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("assistant")

DERIVED_DIR = "AI/Derived"
_IMG_EXT = r"png|jpe?g|webp|gif|bmp|tiff?"
_WIKI_EMBED = re.compile(rf"!\[\[([^\]|]+\.(?:{_IMG_EXT}))(?:\|[^\]]*)?\]\]", re.IGNORECASE)
_MD_EMBED   = re.compile(rf"!\[[^\]]*\]\(([^)]+\.(?:{_IMG_EXT}))\)", re.IGNORECASE)

_MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp",
         "gif": "image/gif", "bmp": "image/bmp", "tif": "image/tiff", "tiff": "image/tiff"}

OCR_PROMPT = (
    "Transcribe ALL text in this image verbatim — including handwriting. Preserve line "
    "breaks and order. After the transcription, add one line beginning 'Description:' "
    "summarising what the image shows. If there is no text, output only the Description line."
)


def find_image_embeds(content: str) -> list[str]:
    """Image embeds in a note: `![[img.png]]` and `![](path.png)`, de-duplicated."""
    out, seen = [], set()
    for m in list(_WIKI_EMBED.finditer(content)) + list(_MD_EMBED.finditer(content)):
        ref = m.group(1).strip()
        if ref and ref not in seen:
            seen.add(ref)
            out.append(ref)
    return out


def resolve_image_path(vault, embed: str) -> Path | None:
    """Resolve an embed to a file. Tries a direct/relative path, then an Obsidian-style
    basename search anywhere in the vault."""
    vault = Path(vault)
    embed = embed.split("|", 1)[0].strip().replace("\\", "/")
    direct = vault / embed
    if direct.is_file():
        return direct
    name = Path(embed).name
    for p in vault.rglob(name):
        if p.is_file():
            return p
    return None


def _mime_for(path: Path) -> str:
    return _MIME.get(path.suffix.lower().lstrip("."), "image/png")


def tesseract_ocr(image_path: Path) -> str:
    """Local OCR via pytesseract. Returns '' (and logs) if the dependency or binary
    is unavailable — never raises, so OCR degrades gracefully offline."""
    try:
        import pytesseract
        from PIL import Image
    except Exception:
        logger.info("[OCR] pytesseract/Pillow not installed — skipping local OCR.")
        return ""
    try:
        return pytesseract.image_to_string(Image.open(image_path)).strip()
    except Exception as exc:
        logger.warning(f"[OCR] tesseract failed on {image_path.name}: {exc}")
        return ""


def make_vision_fn(router, config: dict | None = None):
    """Build a vision callable `(image_path, private) -> str|None` from the router's
    multimodal providers. For a private note it only uses no-train models; returns None
    when no suitable provider exists (caller then falls back to tesseract)."""
    def _vision(image_path: Path, private: bool) -> str | None:
        registry = getattr(router, "registry", None)
        providers = getattr(router, "_providers", {})
        if registry is None:
            return None
        for key, spec in registry.specs.items():
            if "multimodal" not in [s.lower() for s in spec.strengths]:
                continue
            if private and (spec.trains_on_data or "").lower() != "no":
                continue
            provider = providers.get(key)
            if provider is None or not hasattr(provider, "describe_image"):
                continue
            try:
                b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
                return provider.describe_image(b64, _mime_for(image_path), OCR_PROMPT)
            except Exception as exc:
                logger.warning(f"[OCR] vision via {key} failed: {exc}")
                continue
        return None
    return _vision


def analyze_image(vault, image_rel: str, router, config: dict | None = None,
                  private: bool = False) -> tuple[str, str | None]:
    """Analyse one image (transcribe its text + describe it) for the plugin's paperclip.
    Prefers a free multimodal model (privacy-aware), falls back to local tesseract.
    Returns (text, error)."""
    img = resolve_image_path(vault, image_rel) or (Path(vault) / image_rel)
    if not img.is_file():
        return "", f"image not found: {image_rel}"
    text = None
    vfn = make_vision_fn(router, config or {})
    if vfn is not None:
        try:
            text = vfn(img, private)
        except Exception:
            text = None
    if not (text and text.strip()):
        text = (tesseract_ocr(img) or "").strip()
    if not (text and text.strip()):
        return "", ("no model could read the image (no multimodal provider and no local "
                    "tesseract, or the image has no text)")
    return text.strip(), None


class OcrEngine:
    def __init__(self, vault_path, vision_fn=None, tesseract_fn=tesseract_ocr):
        self._vault       = Path(vault_path)
        self._vision_fn   = vision_fn
        self._tesseract_fn = tesseract_fn

    def ocr_note(self, rel_path: str, private: bool = False) -> dict:
        """OCR every image in a note → write an AI/Derived sidecar. Returns a report."""
        rel_path = rel_path.replace("\\", "/")
        note = self._vault / rel_path
        report = {"images": 0, "ocred": 0, "engine": [], "sidecar": None, "text_chars": 0}
        if not note.is_file():
            report["error"] = f"note not found: {rel_path}"
            return report

        embeds = find_image_embeds(note.read_text(encoding="utf-8"))
        report["images"] = len(embeds)
        if not embeds:
            return report

        sections = []
        for embed in embeds:
            img = resolve_image_path(self._vault, embed)
            if img is None:
                sections.append((embed, "[image not found in vault]", "none"))
                continue
            text, engine = self._ocr_one(img, private)
            if text:
                report["ocred"] += 1
                report["text_chars"] += len(text)
                report["engine"].append(engine)
            sections.append((embed, text or "[no text extracted]", engine))

        sidecar_rel = self._write_sidecar(rel_path, sections)
        report["sidecar"] = sidecar_rel
        return report

    def _ocr_one(self, img: Path, private: bool) -> tuple[str, str]:
        # Prefer vision (better at handwriting); fall back to local tesseract.
        if self._vision_fn is not None:
            try:
                text = self._vision_fn(img, private)
            except Exception:
                text = None
            if text and text.strip():
                return text.strip(), "vision"
        text = self._tesseract_fn(img) if self._tesseract_fn else ""
        return (text.strip(), "tesseract") if text and text.strip() else ("", "none")

    def _write_sidecar(self, rel_path: str, sections: list[tuple[str, str, str]]) -> str:
        stem = rel_path[:-3] if rel_path.endswith(".md") else rel_path
        out = self._vault / DERIVED_DIR / f"{stem}.ocr.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        source_name = Path(rel_path).stem
        lines = [
            "---", "ai-derived: ocr", f"source: {rel_path}",
            f"generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", "---", "",
            f"# OCR of [[{source_name}]]", "",
            "*AI-extracted text from images in the source note. The original is unchanged.*", "",
        ]
        for embed, text, engine in sections:
            lines += [f"## {Path(embed).name}  *(via {engine})*", "", text, ""]
        out.write_text("\n".join(lines), encoding="utf-8")
        logger.info(f"[OCR] Wrote sidecar {DERIVED_DIR}/{stem}.ocr.md")
        return f"{DERIVED_DIR}/{stem}.ocr.md"
