"""Mnemo MCP server (FastMCP).

A thin wrapper over mnemo.core. Every tool returns COMPACT output (stats, a
small digest, or a tiny relevant subgraph) — never raw document text — so both
building and using memory cost almost no Claude tokens. Run with:

    python -m mnemo.server
"""
from __future__ import annotations

import json
import subprocess

from mcp.server.fastmcp import FastMCP

from .core import pipeline, store, index, updater

mcp = FastMCP("mnemo")


def _resolve(project: str) -> str | None:
    if project:
        return project
    projects = store.list_projects()
    return projects[0]["id"] if len(projects) == 1 else None


def _need_project() -> str:
    projects = store.list_projects()
    if not projects:
        return "No projects yet. Build one with memory_build(source_dir=...)."
    ids = ", ".join(p["id"] for p in projects)
    return f"Multiple projects exist — specify `project`. Available: {ids}"


@mcp.tool()
def memory_status() -> str:
    """Check the local memory stack: is Ollama running, are the required models
    pulled (extraction, embedding, vision), is Tesseract available, where is the
    store, and what projects exist. Call this first if anything fails."""
    return json.dumps(pipeline.health(), indent=2)


@mcp.tool()
def memory_build(source_dir: str, project: str = "", model: str = "", vision: str = "",
                 ocr_lang: str = "", max_files: int = 0, reset: bool = False) -> str:
    """Build or rebuild project memory from a folder of documents — fully local, token-free.

    Converts EVERY file in the folder (PDF, DOCX, PPTX, XLSX, and images via OCR +
    a local vision model) to Markdown, extracts a knowledge graph with a local LLM,
    then writes: a compact memory.md digest, an embedding index for retrieval, and
    an interactive HTML mind map. Returns ONLY compact stats + file paths (never
    document text), so this consumes almost no Claude tokens.

    Args:
      source_dir: absolute path to the documents folder.
      project: optional project id (defaults to a slug of the folder name).
      model: optional Ollama extraction model (default qwen2.5:7b).
      vision: image captioning mode: auto | off | force.
      ocr_lang: Tesseract language(s), e.g. "eng" or "eng+ben".
      max_files: cap files processed (for quick tests; 0 = all).
      reset: wipe and rebuild from scratch.

    Note: for large corpora this runs for several minutes — all locally. The
    result is reusable across sessions and projects.
    """
    res = pipeline.build_memory(source_dir, project or None, model=model or None,
                                vision=vision or None, ocr_lang=ocr_lang or None,
                                max_files=max_files or None, reset=reset)
    s = res["steps"]
    return json.dumps({
        "project": res["project"],
        "files_ingested": s["ingest"].get("converted", 0) + s["ingest"].get("cached", 0),
        "duplicates_skipped": s["extract"].get("duplicates_skipped", 0),
        "graph": s["graph"],
        "memory_md_approx_tokens": s["digest"].get("approx_tokens"),
        "index_vectors": s["index"].get("vectors"),
        "mindmap": s["mindmap"].get("path"),
        "store": res["paths"]["store"],
        "next": "Use memory_overview() to load context, or memory_query() to search.",
    }, indent=2)


@mcp.tool()
def memory_update(project: str = "", source_dir: str = "") -> str:
    """Incrementally refresh a project's memory: only changed/new files are
    re-converted, then the graph, digest, index, and mind map are regenerated.
    Token-free. Provide `project` (its stored source folder is reused) or a new
    `source_dir`."""
    pid = _resolve(project) if project else None
    res = pipeline.update_memory(source_dir or None, pid)
    s = res["steps"]
    return json.dumps({"project": res["project"], "graph": s["graph"],
                       "ingest": {k: s["ingest"].get(k) for k in ("total", "converted", "cached")}},
                      indent=2)


@mcp.tool()
def memory_overview(project: str = "") -> str:
    """Load the compact memory.md digest for a project — overview, key entities by
    type, key relationships, and key facts. This is the cheap way to restore
    project context at the start of a session (a few hundred tokens, not whole
    documents). If `project` is omitted and only one exists, that one is used."""
    pid = _resolve(project)
    if not pid:
        return _need_project()
    p = store.memory_md_path(pid)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return f"No memory for project '{pid}'. Build it with memory_build(source_dir=...)."


@mcp.tool()
def memory_query(query: str, project: str = "", k: int = 8, scope: str = "project") -> str:
    """Semantic search over project memory. Returns ONLY the most relevant entities
    and facts (a tiny subgraph with provenance) — not raw documents — so it is very
    token-cheap. Use scope="all" to search across ALL projects (memory is reusable
    between projects)."""
    pid = None if scope == "all" else _resolve(project)
    if scope != "all" and not pid:
        return _need_project()
    return index.format_result_md(index.query(query, project_id=pid, k=k, scope=scope))


@mcp.tool()
def memory_expand(entity: str, project: str = "", depth: int = 1) -> str:
    """Explore one entity's neighborhood: its description, facts, relationships, and
    directly connected entities. Compact output. Use after memory_query/overview to
    drill into something specific."""
    pid = _resolve(project)
    if not pid:
        return _need_project()
    return index.format_expand_md(index.expand(pid, entity, depth=depth))


@mcp.tool()
def memory_stats(project: str = "") -> str:
    """Compact analytics for a project's memory graph: entity / relationship / fact
    counts, a breakdown of entities by type, and the most central entities.
    Read-only; token-cheap."""
    pid = _resolve(project)
    if not pid:
        return _need_project()
    return json.dumps(store.project_stats(pid), indent=2)


@mcp.tool()
def memory_export(dest_dir: str, project: str = "", include_graph: bool = False,
                  include_mindmap: bool = False, as_claude_md: bool = False) -> str:
    """Export a project's memory to a folder so it's reusable in any other chat or
    project — e.g. add the file to a Claude Desktop project's knowledge, or save it
    as a repo's CLAUDE.md. Copies memory.md (+ optionally graph.json / mindmap.html;
    set as_claude_md to name it CLAUDE.md). Returns the written paths."""
    pid = _resolve(project)
    if not pid:
        return _need_project()
    return json.dumps(store.export_memory(pid, dest_dir, include_graph=include_graph,
                                          include_mindmap=include_mindmap, as_claude_md=as_claude_md), indent=2)


@mcp.tool()
def memory_list_projects() -> str:
    """List every project in the global memory store with entity/edge counts and
    source folders. Memory persists across sessions and is reusable across projects."""
    return json.dumps(store.list_projects(), indent=2)


@mcp.tool()
def memory_open_mindmap(project: str = "") -> str:
    """Open the interactive HTML knowledge-graph / mind map for a project in the
    default browser (color-coded by type, searchable, click a node for provenance)."""
    pid = _resolve(project)
    if not pid:
        return _need_project()
    p = store.mindmap_path(pid)
    if not p.exists():
        return f"No mind map for '{pid}'. Build memory first."
    subprocess.run(["open", str(p)], check=False)
    return f"Opened mind map: {p}"


@mcp.tool()
def memory_link(into_project: str, from_project: str, query: str = "", k: int = 20) -> str:
    """Reuse memory across projects: import the most relevant (or, with no query,
    the most central) entities + facts from `from_project` into `into_project`, so
    the target project's memory can answer questions about the source. Imported
    nodes are tagged with their origin. Token-free. (Tip: `memory_query(scope="all")`
    already searches across all projects without importing.)"""
    from .core import reuse
    return json.dumps(reuse.link_projects(into_project, from_project, query=query or None, k=k), indent=2)


@mcp.tool()
def memory_self_update() -> str:
    """Update the Mnemo plugin to the latest GitHub release (fast-forward git pull
    of the plugin checkout, then reinstall). Safe: never discards local changes.
    Returns whether an update was applied and the new version. Restart the session
    to load updated code."""
    info = updater.check_update()
    if not info.get("available"):
        return json.dumps({"updated": False, **info}, indent=2)
    return json.dumps(updater.self_update(), indent=2)


def main() -> None:
    # Best-effort, non-blocking: keep the plugin on the latest release.
    try:
        updater.auto_update_on_start()
    except Exception:
        pass
    mcp.run()


if __name__ == "__main__":
    main()
