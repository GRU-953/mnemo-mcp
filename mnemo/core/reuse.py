"""Cross-project reuse.

Memory is already reusable across projects two ways:
  - the global store keeps every project side-by-side, and
  - `memory_query(scope="all")` searches every project at once.

This module adds an explicit *import* primitive: pull the most relevant (or most
central) entities + facts from one project into another, so project B's memory
"knows about" project A. Imported nodes are id-prefixed and tagged with their
origin project. All local; token-free.
"""
from __future__ import annotations

from . import config, store, index, digest, render
from . import ollama_client as oll


def _select(from_project: str, query: str | None, k: int) -> tuple[list[dict], dict]:
    g = store.load_graph(from_project)
    nodes = g.get("nodes", [])
    if not nodes:
        return [], g
    if query and oll.ping() and oll.has_model(config.EMBED_MODEL):
        res = index.query(query, project_id=from_project, k=k, scope="project")
        ids = [n["id"] for n in res.get("nodes", [])]
        by_id = {n["id"]: n for n in nodes}
        sel = [by_id[i] for i in ids if i in by_id]
        if len(sel) < k:  # top up by centrality
            extra = sorted((n for n in nodes if n["id"] not in set(ids)),
                           key=lambda n: -(n.get("degree", 0) * 2 + n.get("mentions", 0)))
            sel += extra[: k - len(sel)]
        return sel[:k], g
    sel = sorted(nodes, key=lambda n: -(n.get("degree", 0) * 2 + n.get("mentions", 0)))[:k]
    return sel, g


def link_projects(into_project: str, from_project: str, query: str | None = None, k: int = 20) -> dict:
    if into_project == from_project:
        return {"linked": 0, "error": "into and from are the same project"}
    sel, gsrc = _select(from_project, query, k)
    if not sel:
        return {"linked": 0, "error": f"no source nodes in '{from_project}'"}
    sel_ids = {n["id"] for n in sel}

    gdst = store.load_graph(into_project)
    gdst.setdefault("nodes", [])
    gdst.setdefault("edges", [])
    gdst.setdefault("facts", [])
    existing = {n["id"] for n in gdst["nodes"]}
    prefix = f"{from_project}:"

    added = 0
    for n in sel:
        nid = prefix + n["id"]
        if nid in existing:
            continue
        m = dict(n)
        m["id"] = nid
        m["from_project"] = from_project
        gdst["nodes"].append(m)
        existing.add(nid)
        added += 1

    for e in gsrc.get("edges", []):
        if e["source"] in sel_ids and e["target"] in sel_ids:
            gdst["edges"].append({"source": prefix + e["source"], "target": prefix + e["target"],
                                  "relation": e.get("relation", "related to"),
                                  "count": e.get("count", 1), "from_project": from_project})
    for f in gsrc.get("facts", []):
        fids = [prefix + i for i in f.get("nodes", []) if i in sel_ids]
        if fids:
            gdst["facts"].append({"text": f["text"], "nodes": fids,
                                  "file": f.get("file"), "from_project": from_project})

    gdst["stats"] = {"nodes": len(gdst["nodes"]), "edges": len(gdst["edges"]),
                     "facts": len(gdst["facts"])}
    store.save_graph(into_project, gdst)

    # Refresh derived artifacts so imported knowledge is searchable + visible.
    digest.build_digest(into_project, llm_overview=False)
    idx = index.build_index(into_project)
    render.build_mindmap(into_project)

    return {"linked": added, "from": from_project, "into": into_project,
            "into_nodes": len(gdst["nodes"]), "into_edges": len(gdst["edges"]),
            "index_vectors": idx.get("vectors")}
