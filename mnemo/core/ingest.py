"""Ingestion: convert a folder of mixed documents into Markdown, fully locally.

Uses MarkItDown for base conversion, Tesseract for OCR (images + scanned PDFs),
and a local Ollama vision model to caption text-less images/diagrams. Produces
provenance-tagged `.md` files in the project's sources/ directory. Token-free.
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from . import config, store
from . import ollama_client as oll

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".mp4", ".mov", ".m4b", ".mpga"}

_MD_LOCAL = threading.local()


def _md():
    md = getattr(_MD_LOCAL, "md", None)
    if md is None:
        from markitdown import MarkItDown
        md = MarkItDown(enable_plugins=False)
        _MD_LOCAL.md = md
    return md


# ── Tesseract OCR ─────────────────────────────────────────────────────────
def _tesseract_cmd() -> str | None:
    for c in ("/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract", "/usr/bin/tesseract"):
        if os.path.exists(c):
            return c
    return shutil.which("tesseract")


def tesseract_available() -> bool:
    return _tesseract_cmd() is not None


def _ocr_pil(pil, lang: str, psm: int = 3) -> str:
    """OCR a PIL image by piping PNG bytes through the tesseract binary.
    Direct subprocess (decode errors='replace') avoids pytesseract's fragile
    stderr decoding, which crashes on some images."""
    cmd = _tesseract_cmd()
    if not cmd:
        return ""
    try:
        buf = io.BytesIO()
        pil.convert("RGB").save(buf, format="PNG")
        r = subprocess.run(
            [cmd, "stdin", "stdout", "-l", lang, "--psm", str(psm)],
            input=buf.getvalue(), capture_output=True, timeout=240,
        )
        if r.returncode == 0:
            return r.stdout.decode("utf-8", "replace").strip()
    except Exception:
        pass
    return ""


def _ocr_image_file(path: Path, lang: str) -> str:
    try:
        from PIL import Image
        with Image.open(path) as im:
            return _ocr_pil(im, lang)
    except Exception:
        return ""


def _ocr_pdf(path: Path, lang: str, max_pages: int) -> str:
    try:
        import pypdfium2 as pdfium
    except Exception:
        return ""
    out: list[str] = []
    pdf = None
    try:
        pdf = pdfium.PdfDocument(str(path))
        n = min(len(pdf), max_pages)
        for i in range(n):
            try:
                page = pdf[i]
                pil = page.render(scale=2.0).to_pil()
                txt = _ocr_pil(pil, lang)
                if txt:
                    out.append(f"<!-- page {i + 1} -->\n{txt}")
            except Exception:
                continue
    except Exception:
        pass
    finally:
        try:
            if pdf is not None:
                pdf.close()
        except Exception:
            pass
    return "\n\n".join(out)


# ── Vision (local Ollama) ─────────────────────────────────────────────────
# Small vision models (e.g. moondream) return an EMPTY response for long/complex
# prompts, so we use a concise primary prompt and fall back to an even simpler one.
VISION_PROMPTS = [
    "Describe this image in detail. List any text, labels, or numbers. "
    "If it is a diagram or chart, describe its structure.",
    "Describe this image.",
]


def _vision_caption(path: Path, model: str) -> str:
    import base64
    try:
        from PIL import Image
        im = Image.open(path).convert("RGB")
        im.thumbnail((1536, 1536))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return ""
    # Try prompts in order (concise->simple); also retry once for transient cold-load failures.
    for attempt in range(2):
        for prompt in VISION_PROMPTS:
            try:
                resp = oll.generate(prompt, model=model, images=[b64],
                                    temperature=0.0, num_ctx=4096, timeout=180).strip()
                if resp:
                    return resp
            except Exception:
                pass
        time.sleep(1.0)
    return ""


def vision_available(model: str | None = None) -> bool:
    model = model or config.VISION_MODEL
    return oll.ping() and oll.has_model(model)


# ── Audio (optional) ──────────────────────────────────────────────────────
def _transcribe(path: Path) -> str:
    try:
        from faster_whisper import WhisperModel
    except Exception:
        return ""
    try:
        model = WhisperModel(os.environ.get("MNEMO_WHISPER_MODEL", "base"),
                            device="cpu", compute_type="int8")
        segments, _ = model.transcribe(str(path), beam_size=1)
        return " ".join(s.text.strip() for s in segments).strip()
    except Exception:
        return ""


# ── Per-file conversion ───────────────────────────────────────────────────
def convert_file(
    path: str | Path,
    *,
    ocr_mode: str | None = None,
    ocr_lang: str | None = None,
    ocr_max_pages: int | None = None,
    vision_mode: str | None = None,
    vision_model: str | None = None,
) -> dict:
    path = Path(path)
    ext = path.suffix.lower()
    ocr_mode = ocr_mode or config.OCR_MODE
    ocr_lang = ocr_lang or config.OCR_LANG
    ocr_max_pages = ocr_max_pages or config.OCR_MAX_PAGES
    vision_mode = vision_mode or config.VISION_MODE
    vision_model = vision_model or config.VISION_MODEL

    parts: list[str] = []
    method: list[str] = []

    base = ""
    if ext not in AUDIO_EXTS:
        try:
            base = (_md().convert(str(path)).markdown or "").strip()
        except Exception:
            base = ""
    if base:
        parts.append(base)
        method.append("markitdown")

    ocr_ok = (ocr_mode != "off") and tesseract_available()
    vis_ok = (vision_mode != "off") and vision_available(vision_model)

    if ext in IMAGE_EXTS:
        if ocr_ok:
            t = _ocr_image_file(path, ocr_lang)
            if t:
                parts.append(f"## OCR text\n\n{t}")
                method.append("ocr")
        # Business-doc images are usually diagrams/charts/slides where a vision
        # caption captures structure that OCR mangles. In auto/force, caption all images.
        if vis_ok and vision_mode in ("auto", "force"):
            cap = _vision_caption(path, vision_model)
            if cap:
                parts.append(f"## Image description\n\n{cap}")
                method.append("vision")
    elif ext == ".pdf":
        need_ocr = ocr_ok and (ocr_mode in ("force", "hybrid") or (ocr_mode == "auto" and len(base) < 200))
        if need_ocr:
            t = _ocr_pdf(path, ocr_lang, ocr_max_pages)
            if t:
                parts.append(f"## OCR text\n\n{t}" if base else t)
                method.append("ocr-pdf")
    elif ext in AUDIO_EXTS:
        t = _transcribe(path)
        if t:
            parts.append(f"## Transcript\n\n{t}")
            method.append("transcribe")

    md_text = "\n\n".join(p for p in parts if p).strip()
    return {"markdown": md_text, "method": "+".join(method) or "none", "chars": len(md_text)}


def _front_matter(path: Path, src_root: Path, res: dict) -> str:
    try:
        rel = path.relative_to(src_root)
    except Exception:
        rel = path.name
    return (
        f"<!-- mnemo-source: {rel} -->\n"
        f"<!-- mnemo-method: {res['method']} | chars: {res['chars']} -->\n\n"
        f"# {path.name}\n\n"
    )


# ── Directory ingestion ───────────────────────────────────────────────────
def iter_source_files(source_dir: str | Path) -> list[Path]:
    src = Path(source_dir).expanduser()
    files: list[Path] = []
    if not src.exists():
        return files
    for p in sorted(src.rglob("*")):
        if p.is_dir():
            continue
        if p.name in config.SKIP_NAMES or p.name.startswith("._"):
            continue
        if p.suffix.lower() in config.SKIP_EXTS:
            continue
        files.append(p)
    return files


def _default_workers() -> int:
    """Auto-size the ingestion pool to the machine. Conversion is CPU/IO-bound
    (MarkItDown parse, Tesseract subprocess, PDF render), which threads parallelize
    well across Apple-silicon cores; capped to avoid oversubscription."""
    if config.INGEST_WORKERS and config.INGEST_WORKERS > 0:
        return config.INGEST_WORKERS
    return max(2, min(8, (os.cpu_count() or 4)))


def ingest_dir(
    source_dir: str | Path,
    project_id: str,
    *,
    incremental: bool = True,
    max_files: int | None = None,
    workers: int | None = None,
    progress: Callable[[int, int, str, str], None] | None = None,
    **opts: Any,
) -> dict:
    src = Path(source_dir).expanduser()
    proj = store.ensure_project(project_id)
    sources_root = proj / "sources"
    manifest = store.read_json(store.manifest_path(project_id), {}) if incremental else {}

    files = iter_source_files(src)
    if max_files:
        files = files[:max_files]
    total = len(files)

    results: list[dict] = []
    counts = {"converted": 0, "cached": 0, "empty": 0, "done": 0}
    new_manifest: dict[str, Any] = {}

    # Partition into already-cached vs needs-conversion (hashing is cheap, serial).
    to_convert: list[tuple] = []
    for f in files:
        rel = f.relative_to(src)
        try:
            h = store.file_hash(f)
        except Exception:
            h = None
        out_md = (sources_root / rel)
        out_md = out_md.with_suffix(out_md.suffix + ".md")
        prev = manifest.get(str(rel))
        if incremental and prev and prev.get("hash") == h and out_md.exists():
            new_manifest[str(rel)] = prev
            counts["cached"] += 1
            counts["done"] += 1
            results.append({"file": str(rel), "status": "cached", "chars": prev.get("chars", 0)})
            if progress:
                progress(counts["done"], total, str(rel), "cached")
        else:
            to_convert.append((f, rel, h, out_md))

    def _convert(task: tuple) -> tuple:
        f, rel, h, out_md = task
        try:
            res = convert_file(f, **opts)
        except Exception:
            res = {"markdown": "", "method": "error", "chars": 0}
        return (f, rel, h, out_md, res)

    def _record(f: Path, rel, h, out_md, res: dict) -> None:
        if res["chars"] > 0:
            store.write_text(out_md, _front_matter(f, src, res) + res["markdown"])
            counts["converted"] += 1
            status = "converted"
        else:
            counts["empty"] += 1
            status = "empty"
        new_manifest[str(rel)] = {
            "hash": h, "chars": res["chars"], "method": res["method"],
            "md": str(out_md.relative_to(proj)) if res["chars"] > 0 else None,
        }
        results.append({"file": str(rel), "status": status, "chars": res["chars"], "method": res["method"]})
        counts["done"] += 1
        if progress:
            progress(counts["done"], total, str(rel), status)

    nworkers = workers or _default_workers()
    if nworkers > 1 and len(to_convert) > 1:
        # convert_file runs in worker threads; all writes/progress happen on the
        # main thread as futures complete, so shared state stays thread-safe.
        with ThreadPoolExecutor(max_workers=nworkers) as ex:
            for fut in as_completed([ex.submit(_convert, t) for t in to_convert]):
                _record(*fut.result())
    else:
        for t in to_convert:
            _record(*_convert(t))

    store.write_json(store.manifest_path(project_id), new_manifest)
    return {
        "total": total,
        "converted": counts["converted"],
        "cached": counts["cached"],
        "empty_or_failed": counts["empty"],
        "workers": nworkers,
        "sources_dir": str(sources_root),
        "files": results,
    }
