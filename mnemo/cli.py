"""Mnemo command-line interface.

Exposes the full pipeline so every capability is testable without the MCP
transport. The MCP server (mnemo/server.py) is a thin wrapper over the same
core functions.

Usage:
  mnemo status
  mnemo build --source <dir> [--project <id>] [--reset]
  mnemo overview [--project <id>]
  mnemo query "<question>" [--project <id>] [-k 8] [--scope project|all]
  mnemo expand "<entity>" [--project <id>] [--depth 1]
  mnemo list
  mnemo mindmap [--project <id>]
"""
from __future__ import annotations

import argparse
import json
import sys

from .core import pipeline, store, index


def _progress(stage: str, msg: str) -> None:
    print(f"  [{stage}] {msg}", file=sys.stderr, flush=True)


def _resolve_project(project: str | None) -> str | None:
    if project:
        return project
    projects = store.list_projects()
    if len(projects) == 1:
        return projects[0]["id"]
    return None


def cmd_status(a: argparse.Namespace) -> int:
    print(json.dumps(pipeline.health(), indent=2))
    return 0


def cmd_build(a: argparse.Namespace) -> int:
    res = pipeline.build_memory(
        a.source, a.project, model=a.model, embed_model=a.embed_model,
        vision=a.vision, ocr_lang=a.ocr_lang, max_files=a.max_files,
        reset=a.reset, llm_overview=not a.no_overview, incremental=not a.reset,
        progress=_progress,
    )
    s = res["steps"]
    summary = {
        "project": res["project"],
        "ingest": {k: s["ingest"].get(k) for k in ("total", "converted", "cached", "empty_or_failed")},
        "extract": s["extract"],
        "graph": s["graph"],
        "digest": s["digest"],
        "index": s["index"],
        "mindmap": s["mindmap"],
        "paths": res["paths"],
    }
    print(json.dumps(summary, indent=2))
    return 0


def cmd_update(a: argparse.Namespace) -> int:
    project = _resolve_project(a.project)
    res = pipeline.update_memory(a.source, project, progress=_progress)
    print(json.dumps({"project": res["project"], "steps": {
        k: res["steps"][k] for k in ("ingest", "extract", "graph", "digest", "index", "mindmap")
    }}, indent=2))
    return 0


def cmd_overview(a: argparse.Namespace) -> int:
    project = _resolve_project(a.project)
    if not project:
        print("Specify --project (multiple or no projects found). Try: mnemo list", file=sys.stderr)
        return 1
    p = store.memory_md_path(project)
    if p.exists():
        print(p.read_text(encoding="utf-8"))
        return 0
    print(f"No memory for project '{project}'. Build it: mnemo build --source <dir> --project {project}",
          file=sys.stderr)
    return 1


def cmd_query(a: argparse.Namespace) -> int:
    project = _resolve_project(a.project) if a.scope != "all" else None
    if a.scope != "all" and not project:
        print("Specify --project or use --scope all", file=sys.stderr)
        return 1
    res = index.query(a.query, project_id=project, k=a.k, scope=a.scope)
    print(json.dumps(res, indent=2) if a.json else index.format_result_md(res))
    return 0


def cmd_expand(a: argparse.Namespace) -> int:
    project = _resolve_project(a.project)
    if not project:
        print("Specify --project", file=sys.stderr)
        return 1
    res = index.expand(project, a.entity, depth=a.depth)
    print(json.dumps(res, indent=2) if a.json else index.format_expand_md(res))
    return 0


def cmd_list(a: argparse.Namespace) -> int:
    print(json.dumps(store.list_projects(), indent=2))
    return 0


def cmd_mindmap(a: argparse.Namespace) -> int:
    import subprocess
    project = _resolve_project(a.project)
    if not project:
        print("Specify --project", file=sys.stderr)
        return 1
    p = store.mindmap_path(project)
    if not p.exists():
        print(f"No mind map for '{project}'. Build memory first.", file=sys.stderr)
        return 1
    print(str(p))
    if not a.no_open:
        subprocess.run(["open", str(p)], check=False)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mnemo", description="Local, token-free graph memory for Claude.")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("status", help="check local stack (Ollama, models, Tesseract, store)")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("build", help="build memory from a folder")
    sp.add_argument("--source", required=True, help="source directory of documents")
    sp.add_argument("--project", help="project id (default: slug of folder name)")
    sp.add_argument("--model", help="Ollama extraction model (default qwen2.5:7b)")
    sp.add_argument("--embed-model", dest="embed_model", help="Ollama embedding model")
    sp.add_argument("--vision", choices=["auto", "off", "force"], help="image captioning mode")
    sp.add_argument("--ocr-lang", dest="ocr_lang", help="tesseract langs, e.g. eng+ben")
    sp.add_argument("--max-files", dest="max_files", type=int, help="limit number of files (testing)")
    sp.add_argument("--reset", action="store_true", help="wipe and rebuild from scratch")
    sp.add_argument("--no-overview", action="store_true", help="skip the LLM-written overview")
    sp.set_defaults(func=cmd_build)

    sp = sub.add_parser("update", help="incremental rebuild (changed files only)")
    sp.add_argument("--project")
    sp.add_argument("--source")
    sp.set_defaults(func=cmd_update)

    sp = sub.add_parser("overview", help="print the compact memory.md digest")
    sp.add_argument("--project")
    sp.set_defaults(func=cmd_overview)

    sp = sub.add_parser("query", help="semantic memory query (compact result)")
    sp.add_argument("query")
    sp.add_argument("--project")
    sp.add_argument("-k", type=int, default=8)
    sp.add_argument("--scope", choices=["project", "all"], default="project")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_query)

    sp = sub.add_parser("expand", help="explore an entity's neighborhood")
    sp.add_argument("entity")
    sp.add_argument("--project")
    sp.add_argument("--depth", type=int, default=1)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_expand)

    sp = sub.add_parser("list", help="list projects in the store")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("mindmap", help="open the HTML mind map")
    sp.add_argument("--project")
    sp.add_argument("--no-open", action="store_true")
    sp.set_defaults(func=cmd_mindmap)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except Exception as e:  # surface errors cleanly
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
