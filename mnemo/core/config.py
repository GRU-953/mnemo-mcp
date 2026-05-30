"""Central configuration. Everything is overridable via environment variables
so the same plugin works on any machine without code edits."""
from __future__ import annotations

import os
import re
from pathlib import Path

# ── Global store (reusable across projects; never published) ──────────────
def store_root() -> Path:
    p = os.environ.get("MNEMO_HOME") or os.path.join(os.path.expanduser("~"), ".claude-memory")
    return Path(p).expanduser()

PROJECTS_DIRNAME = "projects"
SHARED_DIRNAME = "shared"

# ── Local models (free / open-source, served by Ollama) ───────────────────
EXTRACT_MODEL = os.environ.get("MNEMO_EXTRACT_MODEL", "qwen2.5:7b")
EMBED_MODEL = os.environ.get("MNEMO_EMBED_MODEL", "nomic-embed-text")
VISION_MODEL = os.environ.get("MNEMO_VISION_MODEL", "moondream")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
OLLAMA_IDLE_TIMEOUT = int(os.environ.get("OLLAMA_IDLE_TIMEOUT", "300"))

# ── Ingestion (document -> Markdown) ──────────────────────────────────────
OCR_MODE = os.environ.get("MNEMO_OCR", "auto")          # auto | off | force | hybrid
OCR_LANG = os.environ.get("MNEMO_OCR_LANG", "eng")      # e.g. "eng+ben"
VISION_MODE = os.environ.get("MNEMO_VISION", "auto")    # auto | off | force
OCR_MAX_PAGES = int(os.environ.get("MNEMO_OCR_MAX_PAGES", "60"))
INGEST_WORKERS = int(os.environ.get("MNEMO_WORKERS", "0"))  # 0 -> auto

# Pointer-stub / junk extensions to skip (Google Drive online files have no content)
SKIP_EXTS = {
    ".gdoc", ".gslides", ".gsheet", ".gdrive", ".gform", ".gjam",
    ".gsite", ".gmap", ".gtable", ".glink", ".lnk", ".url", ".webloc",
}
SKIP_NAMES = {".DS_Store", ".localized", "Icon\r"}

# ── Chunking / extraction ─────────────────────────────────────────────────
CHUNK_WORDS = int(os.environ.get("MNEMO_CHUNK_WORDS", "1400"))
CHUNK_OVERLAP_WORDS = int(os.environ.get("MNEMO_CHUNK_OVERLAP", "100"))
EXTRACT_TEMPERATURE = float(os.environ.get("MNEMO_EXTRACT_TEMP", "0.0"))
EXTRACT_NUM_CTX = int(os.environ.get("MNEMO_NUM_CTX", "8192"))
MAX_CHUNKS_PER_DOC = int(os.environ.get("MNEMO_MAX_CHUNKS_PER_DOC", "14"))
# Per-chunk output caps — keeping output small is the #1 speed lever for local LLMs.
MAX_ENTITIES_PER_CHUNK = int(os.environ.get("MNEMO_MAX_ENT_CHUNK", "10"))
MAX_FACTS_PER_CHUNK = int(os.environ.get("MNEMO_MAX_FACT_CHUNK", "5"))

# ── Entity resolution ─────────────────────────────────────────────────────
MERGE_COSINE_THRESHOLD = float(os.environ.get("MNEMO_MERGE_COSINE", "0.86"))
MERGE_FUZZY_THRESHOLD = float(os.environ.get("MNEMO_MERGE_FUZZY", "0.90"))

# ── Retrieval ─────────────────────────────────────────────────────────────
DEFAULT_QUERY_K = int(os.environ.get("MNEMO_QUERY_K", "8"))

# ── Controlled entity vocabulary (keeps the graph clean & comparable) ─────
ENTITY_TYPES = [
    "Person", "Organization", "Project", "Document", "Policy", "Product",
    "Location", "Milestone", "Metric", "Process", "Issue", "Concept",
    "Event", "System",
]

# Color per type, used by the HTML mind map.
TYPE_COLORS = {
    "Person": "#e6550d",
    "Organization": "#3182bd",
    "Project": "#9e4dd6",
    "Document": "#7b7b7b",
    "Policy": "#31a354",
    "Product": "#e7ba52",
    "Location": "#17becf",
    "Milestone": "#d6616b",
    "Metric": "#2ca02c",
    "Process": "#1f77b4",
    "Issue": "#d62728",
    "Concept": "#8c6d31",
    "Event": "#bd9e39",
    "System": "#637939",
    "_default": "#999999",
}


def slugify(text: str) -> str:
    """Filesystem/identifier-safe slug."""
    s = re.sub(r"[^\w\s-]", "", str(text).strip().lower())
    s = re.sub(r"[\s_-]+", "-", s).strip("-")
    return s or "untitled"
