"""Extraction: turn Markdown into a raw knowledge graph using a local LLM.

Each document is chunked (heading-aware) and sent to Ollama (qwen2.5:7b by
default) with a forced-JSON schema. We collect entities, relations, and atomic
facts, each tagged with provenance (source file + chunk). All local; no tokens.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from . import config, store
from . import ollama_client as oll

EXTRACT_SYSTEM = (
    "You are a precise knowledge-graph extraction engine. Extract ONLY the most "
    "important entities, their relationships, and a few key atomic facts. Use "
    "canonical, specific names (not pronouns). Be terse. Output ONLY compact valid "
    "JSON matching the schema — no prose, no markdown, no repetition."
)


def _schema_hint() -> str:
    types = ", ".join(config.ENTITY_TYPES)
    me = config.MAX_ENTITIES_PER_CHUNK
    mf = config.MAX_FACTS_PER_CHUNK
    return (
        "Output compact JSON with exactly these keys:\n"
        '{\n'
        '  "entities": [ {"name": "<canonical name>", "type": "<one of: ' + types + '>", '
        '"description": "<<=12 words>", "aliases": ["<other names>"]} ],\n'
        '  "relations": [ {"source": "<entity>", "relation": "<1-3 word verb phrase>", '
        '"target": "<entity>"} ],\n'
        '  "facts": [ {"text": "<atomic fact, <=22 words>", "entities": ["<names>"]} ]\n'
        '}\n'
        f"HARD LIMITS: at most {me} entities (the most important only), at most "
        f"{me} relations, at most {mf} facts. Descriptions <=12 words; facts <=22 words. "
        "Only relations where both endpoints are entities. Never repeat. Never invent."
    )


# ── Chunking ──────────────────────────────────────────────────────────────
def chunk_markdown(text: str, words: int | None = None, overlap: int | None = None) -> list[str]:
    words = words or config.CHUNK_WORDS
    overlap = overlap or config.CHUNK_OVERLAP_WORDS

    # Group lines into blocks, starting a new block at markdown headings.
    blocks: list[str] = []
    cur: list[str] = []
    for ln in text.split("\n"):
        if re.match(r"^#{1,6}\s", ln) and cur:
            blocks.append("\n".join(cur))
            cur = [ln]
        else:
            cur.append(ln)
    if cur:
        blocks.append("\n".join(cur))

    # Split oversized heading-less blocks (e.g. big spreadsheet tables) into
    # word-bounded pieces, so no single chunk overflows the model context window.
    sized: list[str] = []
    for b in blocks:
        bw = b.split()
        if len(bw) <= words:
            sized.append(b)
        else:
            for i in range(0, len(bw), words):
                sized.append(" ".join(bw[i:i + words]))
    blocks = sized

    chunks: list[str] = []
    buf: list[str] = []
    bufw = 0
    for b in blocks:
        w = len(b.split())
        if bufw + w > words and buf:
            chunks.append("\n".join(buf).strip())
            tail = " ".join("\n".join(buf).split()[-overlap:]) if overlap else ""
            buf = [tail] if tail else []
            bufw = len(tail.split()) if tail else 0
        buf.append(b)
        bufw += w
        # A single huge block: hard-split by words.
        if bufw > words * 2:
            chunks.append("\n".join(buf).strip())
            buf, bufw = [], 0
    if buf:
        chunks.append("\n".join(buf).strip())
    return [c for c in chunks if c and len(c.split()) >= 3]


# ── Normalization ─────────────────────────────────────────────────────────
def _clean_name(s: Any) -> str:
    s = re.sub(r"\s+", " ", str(s or "").strip())
    return s.strip(" \t\n\r\"'`*_#")


def _norm_type(t: Any) -> str:
    t = str(t or "").strip().title()
    return t if t in config.ENTITY_TYPES else "Concept"


def extract_chunk(text: str, *, model: str | None = None, source: dict | None = None) -> dict:
    """Extract a single chunk -> {entities, relations, facts} with provenance."""
    model = model or config.EXTRACT_MODEL
    src = source or {}
    prompt = f"{_schema_hint()}\n\nDOCUMENT CHUNK:\n\"\"\"\n{text}\n\"\"\"\n\nJSON:"
    try:
        raw = oll.generate(
            prompt, model=model, system=EXTRACT_SYSTEM, fmt="json",
            temperature=config.EXTRACT_TEMPERATURE, num_ctx=config.EXTRACT_NUM_CTX,
            num_predict=1024, keep_alive="30m", timeout=400,
        )
    except Exception as e:
        return {"entities": [], "relations": [], "facts": [], "error": str(e)}
    data = oll.parse_json(raw) or {}

    entities: list[dict] = []
    seen_names: set[str] = set()
    for e in (data.get("entities") or []):
        if not isinstance(e, dict):
            continue
        name = _clean_name(e.get("name"))
        if not name or len(name) > 120:
            continue
        key = name.lower()
        if key in seen_names:
            continue
        seen_names.add(key)
        aliases = [_clean_name(a) for a in (e.get("aliases") or []) if _clean_name(a)]
        entities.append({
            "name": name,
            "type": _norm_type(e.get("type")),
            "description": _clean_name(e.get("description"))[:240],
            "aliases": [a for a in aliases if a.lower() != key][:6],
            "source": src,
        })

    valid = {e["name"].lower() for e in entities} | {a.lower() for e in entities for a in e["aliases"]}
    relations: list[dict] = []
    for r in (data.get("relations") or []):
        if not isinstance(r, dict):
            continue
        s = _clean_name(r.get("source"))
        o = _clean_name(r.get("target"))
        rel = _clean_name(r.get("relation"))[:60]
        if not s or not o or not rel or s.lower() == o.lower():
            continue
        # Keep relations even if endpoints weren't listed; graph build will create stubs,
        # but prefer ones grounded in extracted entities.
        relations.append({"source": s, "relation": rel, "target": o, "grounded":
                          (s.lower() in valid and o.lower() in valid), "src": src})

    facts: list[dict] = []
    for f in (data.get("facts") or []):
        if isinstance(f, str):
            txt = _clean_name(f)
            ents = []
        elif isinstance(f, dict):
            txt = _clean_name(f.get("text"))
            ents = [_clean_name(x) for x in (f.get("entities") or []) if _clean_name(x)]
        else:
            continue
        if txt and len(txt) >= 8:
            facts.append({"text": txt[:240], "entities": ents[:8], "source": src})

    # Enforce caps as a safety net (the prompt also requests them).
    return {
        "entities": entities[: config.MAX_ENTITIES_PER_CHUNK],
        "relations": relations[: config.MAX_ENTITIES_PER_CHUNK],
        "facts": facts[: config.MAX_FACTS_PER_CHUNK],
    }


# ── Whole-project extraction ──────────────────────────────────────────────
def _iter_source_md(project_id: str) -> list[Path]:
    sources = store.project_dir(project_id) / "sources"
    if not sources.exists():
        return []
    return sorted(p for p in sources.rglob("*.md") if p.is_file())


def extract_project(
    project_id: str,
    *,
    model: str | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> dict:
    model = model or config.EXTRACT_MODEL
    md_files = _iter_source_md(project_id)
    proj = store.project_dir(project_id)

    import hashlib

    all_entities: list[dict] = []
    all_relations: list[dict] = []
    all_facts: list[dict] = []
    n_chunks = 0
    seen_hashes: dict[str, str] = {}
    skipped_dups: list[str] = []

    for fi, mdf in enumerate(md_files):
        rel = str(mdf.relative_to(proj / "sources"))
        text = mdf.read_text(encoding="utf-8", errors="replace")
        # De-duplicate identical content (corpus has docx/pdf pairs & exact copies).
        body = re.sub(r"<!--\s*mnemo-.*?-->", "", text)
        norm = re.sub(r"\s+", " ", body.lower()).strip()
        h = hashlib.md5(norm.encode("utf-8")).hexdigest()
        if len(norm) > 200 and h in seen_hashes:
            skipped_dups.append(rel)
            if progress:
                progress(fi + 1, len(md_files), f"{rel} (duplicate of {seen_hashes[h]}, skipped)")
            continue
        seen_hashes[h] = rel

        chunks = chunk_markdown(text)[: config.MAX_CHUNKS_PER_DOC]
        for ci, ch in enumerate(chunks):
            src = {"file": rel, "chunk": ci}
            res = extract_chunk(ch, model=model, source=src)
            all_entities.extend(res["entities"])
            all_relations.extend(res["relations"])
            all_facts.extend(res["facts"])
            n_chunks += 1
        if progress:
            progress(fi + 1, len(md_files), rel)

    raw = {
        "entities": all_entities,
        "relations": all_relations,
        "facts": all_facts,
        "stats": {"docs": len(md_files), "duplicates_skipped": len(skipped_dups),
                  "chunks": n_chunks, "raw_entities": len(all_entities),
                  "raw_relations": len(all_relations), "raw_facts": len(all_facts)},
    }
    store.write_json(proj / "extractions.json", raw)
    return raw["stats"]
