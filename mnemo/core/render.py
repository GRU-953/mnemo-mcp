"""Render the knowledge graph into a self-contained interactive HTML mind map
(Cytoscape.js). Color-coded by entity type, searchable, with a click-to-explore
provenance panel. Vendored Cytoscape is inlined so the file works offline."""
from __future__ import annotations

import html as _html
import json
from pathlib import Path

from . import config, store


def _repo_root() -> Path:
    # mnemo/core/render.py -> mnemo/core -> mnemo -> <repo root>
    return Path(__file__).resolve().parents[2]


def _html_safe_json(obj) -> str:
    """Serialize to JSON safe for embedding inside an HTML <script> tag.

    Entity names/facts come from arbitrary documents and may contain '</script>'
    or JS line separators; escaping <, >, & and U+2028/U+2029 keeps the data from
    breaking out of the script (HTML injection) while staying valid JSON/JS.
    """
    return (
        json.dumps(obj, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )


def _cytoscape_tag() -> str:
    asset = _repo_root() / "assets" / "cytoscape.min.js"
    if asset.exists():
        try:
            return f"<script>{asset.read_text(encoding='utf-8')}</script>"
        except Exception:
            pass
    return ('<script src="https://cdnjs.cloudflare.com/ajax/libs/'
            'cytoscape/3.30.2/cytoscape.min.js"></script>')


def _score(n: dict) -> int:
    return n.get("degree", 0) * 2 + n.get("mentions", 0)


def build_mindmap(project_id: str, *, max_nodes: int = 250) -> dict:
    g = store.load_graph(project_id)
    nodes = g.get("nodes", [])
    edges = g.get("edges", [])
    meta = store.load_meta(project_id)

    keep = sorted(nodes, key=lambda n: -_score(n))[:max_nodes]
    keep_ids = {n["id"] for n in keep}

    elements: list[dict] = []
    for n in keep:
        elements.append({"data": {
            "id": n["id"], "label": n["name"], "type": n.get("type", "Concept"),
            "degree": n.get("degree", 0), "description": n.get("description", ""),
            "facts": n.get("facts", [])[:8], "sources": n.get("sources", [])[:6],
        }})
    ei = 0
    for e in edges:
        if e["source"] in keep_ids and e["target"] in keep_ids:
            elements.append({"data": {"id": f"e{ei}", "source": e["source"],
                                      "target": e["target"], "label": e.get("relation", "")}})
            ei += 1

    data = {
        "elements": elements,
        "typeColors": config.TYPE_COLORS,
        "meta": {"project": project_id, "name": meta.get("name", project_id)},
    }

    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader(str(_repo_root() / "templates")), autoescape=False)
    tmpl = env.get_template("mindmap.html.j2")
    html = tmpl.render(
        project_name=_html.escape(str(meta.get("name", project_id))),
        stats_line=f"{len(keep)} of {len(nodes)} entities · {ei} relationships",
        generated=_html.escape(str(g.get("generated", ""))),
        cytoscape_tag=_cytoscape_tag(),
        data_json=_html_safe_json(data),
    )
    out = store.mindmap_path(project_id)
    store.write_text(out, html)
    return {"path": str(out), "nodes": len(keep), "edges": ei,
            "pruned": max(0, len(nodes) - len(keep)), "bytes": len(html)}
