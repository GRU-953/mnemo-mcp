"""Embedding index + retrieval. This is the token-saver at *use* time:
memory_query embeds the query locally and returns only the most relevant nodes
and facts (a tiny subgraph) instead of dumping documents into Claude's context.
"""
from __future__ import annotations

from pathlib import Path

from . import config, store
from . import ollama_client as oll


def _node_text(n: dict) -> str:
    parts = [f"{n['name']} ({n.get('type', '')})."]
    if n.get("description"):
        parts.append(n["description"])
    if n.get("aliases"):
        parts.append("Also known as: " + ", ".join(n["aliases"][:4]))
    if n.get("facts"):
        parts.append(" ".join(n["facts"][:5]))
    return " ".join(parts)


def build_index(project_id: str, *, model: str | None = None) -> dict:
    import numpy as np
    model = model or config.EMBED_MODEL
    g = store.load_graph(project_id)
    nodes = g.get("nodes", [])
    facts = g.get("facts", [])

    items: list[dict] = []
    texts: list[str] = []
    for n in nodes:
        items.append({"kind": "node", "id": n["id"], "name": n["name"], "type": n.get("type"),
                      "description": n.get("description", ""), "sources": n.get("sources", []),
                      "facts": n.get("facts", [])[:6]})
        texts.append(_node_text(n))
    for f in facts:
        if f.get("text"):
            items.append({"kind": "fact", "text": f["text"], "nodes": f.get("nodes", []),
                          "file": f.get("file")})
            texts.append(f["text"])

    if not texts:
        return {"vectors": 0, "dim": 0}

    vecs = np.asarray(oll.embed(texts, model=model), dtype="float32")
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    vecs = vecs / norms

    idir = store.project_dir(project_id) / "index"
    idir.mkdir(parents=True, exist_ok=True)
    np.save(idir / "vectors.npy", vecs)
    store.write_json(idir / "items.json", items)
    store.write_json(idir / "index_meta.json",
                     {"model": model, "dim": int(vecs.shape[1]),
                      "count": int(vecs.shape[0]), "updated": store.now_iso()})
    return {"vectors": int(vecs.shape[0]), "dim": int(vecs.shape[1])}


def _load_index(project_id: str):
    import numpy as np
    idir = store.project_dir(project_id) / "index"
    vp, ip = idir / "vectors.npy", idir / "items.json"
    if not vp.exists() or not ip.exists():
        return None, None
    try:
        return np.load(vp), store.read_json(ip, [])
    except Exception:
        return None, None


def query(query_text: str, *, project_id: str | None = None, k: int | None = None,
          scope: str = "project", model: str | None = None) -> dict:
    import numpy as np
    model = model or config.EMBED_MODEL
    k = k or config.DEFAULT_QUERY_K

    emb = oll.embed([query_text], model=model)
    if not emb:
        return {"query": query_text, "scope": scope, "nodes": [], "facts": [], "error": "embedding failed"}
    q = np.asarray(emb[0], dtype="float32")
    nq = np.linalg.norm(q)
    if nq:
        q = q / nq

    targets: list[str] = []
    if scope == "all":
        targets = [p["id"] for p in store.list_projects()]
    elif project_id:
        targets = [project_id]

    hits: list[tuple[float, str, dict]] = []
    for pid in targets:
        vecs, items = _load_index(pid)
        if vecs is None or items is None:
            continue
        sims = vecs @ q
        order = np.argsort(-sims)[: max(k * 3, 20)]
        for i in order:
            hits.append((float(sims[i]), pid, items[int(i)]))
    hits.sort(key=lambda x: -x[0])

    out_nodes: list[dict] = []
    out_facts: list[dict] = []
    seen_n: set[tuple] = set()
    seen_f: set[str] = set()
    for score, pid, it in hits:
        if it["kind"] == "node" and len(out_nodes) < k:
            key = (pid, it["id"])
            if key in seen_n:
                continue
            seen_n.add(key)
            out_nodes.append({"project": pid, "id": it["id"], "name": it["name"],
                              "type": it.get("type"), "description": it.get("description", ""),
                              "facts": it.get("facts", [])[:3], "sources": it.get("sources", [])[:3],
                              "score": round(score, 3)})
        elif it["kind"] == "fact" and len(out_facts) < k:
            t = it["text"].strip()
            if t.lower() in seen_f:
                continue
            seen_f.add(t.lower())
            out_facts.append({"project": pid, "text": t, "file": it.get("file"),
                              "score": round(score, 3)})
        if len(out_nodes) >= k and len(out_facts) >= k:
            break

    return {"query": query_text, "scope": scope, "nodes": out_nodes, "facts": out_facts}


def _find_node(nodes: list[dict], entity: str) -> dict | None:
    import difflib
    e = entity.strip().lower()
    by_id = {n["id"]: n for n in nodes}
    if entity in by_id:
        return by_id[entity]
    for n in nodes:
        if n["name"].lower() == e or e in {a.lower() for a in n.get("aliases", [])}:
            return n
    cands = [n for n in nodes if e in n["name"].lower()]
    if cands:
        return max(cands, key=lambda n: n.get("degree", 0))
    names = [n["name"].lower() for n in nodes]
    match = difflib.get_close_matches(e, names, n=1, cutoff=0.6)
    if match:
        return nodes[names.index(match[0])]
    return None


def expand(project_id: str, entity: str, depth: int = 1) -> dict:
    """Return a compact neighborhood subgraph around an entity."""
    g = store.load_graph(project_id)
    nodes = g.get("nodes", [])
    edges = g.get("edges", [])
    nid = {n["id"]: n for n in nodes}
    center = _find_node(nodes, entity)
    if not center:
        return {"found": False, "entity": entity}

    keep = {center["id"]}
    frontier = {center["id"]}
    for _ in range(max(1, depth)):
        nxt: set[str] = set()
        for e in edges:
            if e["source"] in frontier and e["target"] not in keep:
                nxt.add(e["target"])
            if e["target"] in frontier and e["source"] not in keep:
                nxt.add(e["source"])
        keep |= nxt
        frontier = nxt
        if not frontier:
            break

    rels = [e for e in edges if e["source"] in keep and e["target"] in keep
            and (e["source"] == center["id"] or e["target"] == center["id"])]
    neighbors = [{"id": i, "name": nid[i]["name"], "type": nid[i].get("type")}
                 for i in keep if i != center["id"] and i in nid]
    return {
        "found": True,
        "center": {"id": center["id"], "name": center["name"], "type": center.get("type"),
                   "description": center.get("description", ""), "facts": center.get("facts", [])[:8],
                   "sources": center.get("sources", [])[:6]},
        "relations": [{"source": nid.get(e["source"], {}).get("name", e["source"]),
                       "relation": e["relation"],
                       "target": nid.get(e["target"], {}).get("name", e["target"])} for e in rels][:25],
        "neighbors": neighbors[:30],
    }


def format_expand_md(res: dict) -> str:
    if not res.get("found"):
        return f"Entity not found: {res.get('entity')}. Try memory_query instead."
    c = res["center"]
    lines = [f"### {c['name']} ({c.get('type')})"]
    if c.get("description"):
        lines.append(c["description"])
    if c.get("facts"):
        lines.append("\n**Facts**")
        lines += [f"- {f}" for f in c["facts"]]
    if res.get("relations"):
        lines.append("\n**Relationships**")
        lines += [f"- {r['source']} **{r['relation']}** {r['target']}" for r in res["relations"]]
    if c.get("sources"):
        lines.append(f"\n_Sources: {', '.join(c['sources'][:4])}_")
    return "\n".join(lines)


def format_result_md(res: dict) -> str:
    lines = [f"### Memory matches for: {res['query']}"]
    multi = res.get("scope") == "all"
    if res.get("nodes"):
        lines.append("\n**Entities**")
        for n in res["nodes"]:
            tag = f"  _[{n['project']}]_" if multi else ""
            d = f" — {n['description']}" if n.get("description") else ""
            lines.append(f"- **{n['name']}** ({n.get('type')}){d}{tag}")
            for f in n.get("facts", [])[:2]:
                lines.append(f"    - {f}")
            if n.get("sources"):
                lines.append(f"    - _source: {', '.join(n['sources'][:2])}_")
    if res.get("facts"):
        lines.append("\n**Facts**")
        for f in res["facts"]:
            tag = f"  _[{f['project']}]_" if multi else ""
            src = f"  _({f['file']})_" if f.get("file") else ""
            lines.append(f"- {f['text']}{src}{tag}")
    if not res.get("nodes") and not res.get("facts"):
        lines.append("\n(no matches — run memory_overview, or rebuild memory for this project)")
    return "\n".join(lines)
