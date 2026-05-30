"""Global memory store layout & IO. The store is reusable across projects and
lives outside any repo (default ~/.claude-memory/)."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from . import config


# ── Paths ─────────────────────────────────────────────────────────────────
def projects_dir() -> Path:
    return config.store_root() / config.PROJECTS_DIRNAME


def shared_dir() -> Path:
    d = config.store_root() / config.SHARED_DIRNAME
    return d


def project_dir(project_id: str) -> Path:
    return projects_dir() / project_id


def ensure_project(project_id: str) -> Path:
    d = project_dir(project_id)
    (d / "sources").mkdir(parents=True, exist_ok=True)
    (d / "index").mkdir(parents=True, exist_ok=True)
    return d


def ensure_shared() -> Path:
    d = shared_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── JSON IO ───────────────────────────────────────────────────────────────
def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: str | Path, obj: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: str | Path, text: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# ── Convenience accessors ─────────────────────────────────────────────────
def graph_path(project_id: str) -> Path:
    return project_dir(project_id) / "graph.json"


def memory_md_path(project_id: str) -> Path:
    return project_dir(project_id) / "memory.md"


def mindmap_path(project_id: str) -> Path:
    return project_dir(project_id) / "mindmap.html"


def meta_path(project_id: str) -> Path:
    return project_dir(project_id) / "meta.json"


def manifest_path(project_id: str) -> Path:
    return project_dir(project_id) / "manifest.json"


def load_graph(project_id: str) -> dict:
    return read_json(graph_path(project_id), {"nodes": [], "edges": []})


def save_graph(project_id: str, graph: dict) -> None:
    write_json(graph_path(project_id), graph)


def load_meta(project_id: str) -> dict:
    return read_json(meta_path(project_id), {})


def save_meta(project_id: str, meta: dict) -> None:
    write_json(meta_path(project_id), meta)


# ── Project discovery ─────────────────────────────────────────────────────
def list_projects() -> list[dict]:
    out: list[dict] = []
    pdir = projects_dir()
    if not pdir.exists():
        return out
    for d in sorted(pdir.iterdir()):
        if not d.is_dir():
            continue
        meta = read_json(d / "meta.json", {})
        g = read_json(d / "graph.json", {"nodes": [], "edges": []})
        out.append({
            "id": d.name,
            "name": meta.get("name", d.name),
            "source_dir": meta.get("source_dir"),
            "nodes": len(g.get("nodes", [])),
            "edges": len(g.get("edges", [])),
            "files": meta.get("files_ingested"),
            "updated": meta.get("updated"),
            "has_mindmap": (d / "mindmap.html").exists(),
        })
    return out


def project_stats(project_id: str) -> dict:
    """Compact analytics for a project's graph (counts, type breakdown, top entities)."""
    from collections import Counter
    g = load_graph(project_id)
    nodes = g.get("nodes", [])
    edges = g.get("edges", [])
    facts = g.get("facts", [])
    meta = load_meta(project_id)
    by_type = Counter(n.get("type", "?") for n in nodes)
    ranked = sorted(nodes, key=lambda n: -(n.get("degree", 0) * 2 + n.get("mentions", 0)))
    return {
        "project": project_id,
        "name": meta.get("name", project_id),
        "source_dir": meta.get("source_dir"),
        "updated": meta.get("updated"),
        "files_ingested": meta.get("files_ingested"),
        "nodes": len(nodes),
        "edges": len(edges),
        "facts": len(facts),
        "entities_by_type": dict(by_type.most_common()),
        "top_entities": [{"name": n["name"], "type": n.get("type"),
                          "degree": n.get("degree", 0), "mentions": n.get("mentions", 0)}
                         for n in ranked[:12]],
    }


# ── Hashing / time ────────────────────────────────────────────────────────
def file_hash(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
