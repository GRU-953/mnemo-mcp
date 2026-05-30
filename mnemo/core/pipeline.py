"""Pipeline orchestration: ingest -> extract -> graph -> digest -> index -> render.

This is the single entry point the CLI and MCP server call. Everything runs
locally; the caller gets back compact stats and file paths (never document text).
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

from . import config, store, ingest, extract, graph, digest, index, render, platform_tuning, lifecycle
from . import ollama_client as oll

Progress = Callable[[str, str], None]


def reset_project(project: str) -> None:
    d = store.project_dir(project)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)


def health() -> dict:
    models = oll.list_models()
    return {
        "ollama": {
            "up": oll.ping(),
            "version": oll.version(),
            "host": config.OLLAMA_HOST,
            "models_installed": models,
            "extract_model": config.EXTRACT_MODEL,
            "extract_ready": oll.has_model(config.EXTRACT_MODEL),
            "embed_model": config.EMBED_MODEL,
            "embed_ready": oll.has_model(config.EMBED_MODEL),
            "vision_model": config.VISION_MODEL,
            "vision_ready": oll.has_model(config.VISION_MODEL),
        },
        "tesseract": ingest.tesseract_available(),
        "hardware": platform_tuning.hardware_info(),
        "ollama_tuning": platform_tuning.ollama_tuning_status(),
        "ollama_lifecycle": lifecycle.status(),
        "ingest_workers": ingest._default_workers(),
        "store": str(config.store_root()),
        "projects": store.list_projects(),
    }


def build_memory(
    source_dir: str,
    project: str | None = None,
    *,
    model: str | None = None,
    embed_model: str | None = None,
    vision: str | None = None,
    ocr_lang: str | None = None,
    max_files: int | None = None,
    reset: bool = False,
    llm_overview: bool = True,
    incremental: bool = True,
    progress: Progress | None = None,
) -> dict:
    source = Path(source_dir).expanduser()
    if not source.exists():
        raise FileNotFoundError(f"source_dir not found: {source}")
    project = project or config.slugify(source.name)

    if not oll.ping():
        raise RuntimeError(
            f"Ollama is not reachable at {config.OLLAMA_HOST}. "
            "Start it with `ollama serve` (or `brew services start ollama`)."
        )
    if reset:
        reset_project(project)

    store.ensure_project(project)
    meta = store.load_meta(project)
    meta.update({
        "name": meta.get("name") or source.name,
        "source_dir": str(source),
        "extract_model": model or config.EXTRACT_MODEL,
        "embed_model": embed_model or config.EMBED_MODEL,
        "updated": store.now_iso(),
    })
    store.save_meta(project, meta)

    def p(stage: str, msg: str) -> None:
        if progress:
            progress(stage, msg)

    steps: dict = {}

    # 1) Ingest
    opts: dict = {}
    if ocr_lang:
        opts["ocr_lang"] = ocr_lang
    if vision:
        opts["vision_mode"] = vision
    p("ingest", f"converting documents in {source} …")
    steps["ingest"] = ingest.ingest_dir(
        str(source), project, incremental=incremental, max_files=max_files,
        progress=(lambda i, n, name, st: p("ingest", f"[{i}/{n}] {st}: {name}")), **opts,
    )

    # 2) Extract
    p("extract", "extracting entities, relations, facts (local LLM) …")
    steps["extract"] = extract.extract_project(
        project, model=model,
        progress=(lambda i, n, name: p("extract", f"[{i}/{n}] {name}")),
    )

    # 3) Graph + entity resolution
    p("graph", "resolving entities and building graph …")
    steps["graph"] = graph.build_graph(project, embed=True, progress=(lambda m: p("graph", m)))

    # 4) Compact digest
    p("digest", "writing memory.md digest …")
    steps["digest"] = digest.build_digest(project, llm_overview=llm_overview, model=model)

    # 5) Embedding index
    p("index", "building retrieval index …")
    steps["index"] = index.build_index(project, model=embed_model)

    # 6) HTML mind map
    p("render", "rendering interactive mind map …")
    steps["mindmap"] = render.build_mindmap(project)

    g = store.load_graph(project)
    meta.update({
        "files_ingested": steps["ingest"].get("converted", 0) + steps["ingest"].get("cached", 0),
        "nodes": len(g.get("nodes", [])),
        "edges": len(g.get("edges", [])),
        "facts": len(g.get("facts", [])),
        "updated": store.now_iso(),
    })
    store.save_meta(project, meta)

    return {
        "project": project,
        "steps": steps,
        "paths": {
            "graph": str(store.graph_path(project)),
            "memory_md": str(store.memory_md_path(project)),
            "mindmap": str(store.mindmap_path(project)),
            "store": str(store.project_dir(project)),
        },
    }


def update_memory(source_dir: str | None = None, project: str | None = None,
                  progress: Progress | None = None, **kw) -> dict:
    """Incremental rebuild — only changed files are re-ingested, then the graph,
    digest, index, and mind map are regenerated."""
    if not project and not source_dir:
        raise ValueError("provide project or source_dir")
    if not source_dir:
        meta = store.load_meta(project)  # type: ignore[arg-type]
        source_dir = meta.get("source_dir")
        if not source_dir:
            raise ValueError(f"no stored source_dir for project '{project}'")
    return build_memory(source_dir, project, incremental=True, progress=progress, **kw)
