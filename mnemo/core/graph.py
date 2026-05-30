"""Graph build + entity resolution.

Consumes raw per-chunk extractions and produces a clean knowledge graph:
- merges duplicate entities (exact-name, alias, then embedding+fuzzy similarity)
- maps relations onto canonical nodes and de-duplicates edges
- attaches atomic facts to nodes
- computes degree centrality
All local (embeddings via nomic-embed-text). Output: graph.json.
"""
from __future__ import annotations

import difflib
import re
from collections import Counter, defaultdict
from typing import Any, Callable

from . import config, store
from . import ollama_client as oll


def _norm(s: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def _fuzzy(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


_YEAR_RE = re.compile(r"^(19|20)\d{2}(\s*[-–—/to]+\s*((19|20)\d{2}\+?|present|now|\+))?$", re.I)
_NUMERIC_RE = re.compile(r"^[-+]?\$?\d[\d,\.]*\s*(%|percent|kw|kv|mw|kg|tco2e?|tons?)?\+?$", re.I)
# Vision-caption / OCR sentence fragments that sometimes surface as "entities".
_CAPTION_START = ("the image", "this image", "image shows", "the photo", "a photo",
                  "the picture", "an image", "the diagram shows")


def _looks_like_sentence(name: str) -> bool:
    """Heuristic: real entity names are short noun phrases, not prose. Drop long
    descriptive fragments (e.g. a vision caption mistaken for an entity)."""
    n = name.strip()
    low = n.lower()
    if low.startswith(_CAPTION_START):
        return True
    return len(n.split()) >= 10


def _refine_type(name: str, type_: str) -> str:
    """Deterministically correct common LLM mistypes by name shape."""
    n = name.strip()
    if _YEAR_RE.match(n):
        return "Milestone"
    if _NUMERIC_RE.match(n):
        return "Metric"
    return type_


class _UF:
    """Union-find for clustering near-duplicate entities."""

    def __init__(self) -> None:
        self.p: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.p.setdefault(x, x)
        root = x
        while self.p[root] != root:
            root = self.p[root]
        while self.p[x] != root:
            self.p[x], x = root, self.p[x]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def build_graph(project_id: str, *, embed: bool = True,
                progress: Callable[[str], None] | None = None) -> dict:
    proj = store.project_dir(project_id)
    raw = store.read_json(proj / "extractions.json", {"entities": [], "relations": [], "facts": []})
    ents = raw.get("entities", [])
    rels = raw.get("relations", [])
    facts = raw.get("facts", [])

    canon: dict[str, dict] = {}
    alias_index: dict[str, str] = {}  # normalized alias/name -> canonical key

    def touch(name: Any, type_: Any, desc: Any, src: dict | None) -> str | None:
        k = _norm(name)
        if not k:
            return None
        k = alias_index.get(k, k)
        n = canon.get(k)
        if n is None:
            n = {"name": str(name).strip(), "type_votes": Counter(), "descs": Counter(),
                 "aliases": set(), "sources": Counter(), "mentions": 0}
            canon[k] = n
        n["mentions"] += 1
        if type_:
            n["type_votes"][type_] += 1
        if desc:
            n["descs"][desc] += 1
        if src and src.get("file"):
            n["sources"][src["file"]] += 1
        return k

    # Junk entities that can leak from provenance markers / OCR artifacts.
    junk = {"mnemo source", "mnemo method", "page", "source", "method", "chunk", "image", "ocr text"}
    if progress:
        progress(f"resolving {len(ents)} raw entities")
    for e in ents:
        raw_name = e.get("name") or ""
        nm = _norm(raw_name)
        if not nm or nm in junk or nm.startswith("mnemo") or _looks_like_sentence(raw_name):
            continue
        k = touch(e.get("name"), e.get("type"), e.get("description", ""), e.get("source"))
        if not k:
            continue
        for a in e.get("aliases", []):
            na = _norm(a)
            if na and na != k and na not in canon and na not in alias_index:
                alias_index[na] = k
                canon[k]["aliases"].add(str(a).strip())

    # ── Embedding + fuzzy merge of near-duplicate canonical entities ──
    keys = list(canon.keys())
    if embed and len(keys) > 1:
        from . import lifecycle
        lifecycle.ensure_up()  # start the LLM on demand; don't gate on the flaky
        try:                   # has_model() which can be empty right after a cold start
            import time as _time
            import numpy as np
            labels = []
            for k in keys:
                tv = canon[k]["type_votes"]
                typ = tv.most_common(1)[0][0] if tv else "Concept"
                labels.append(f"{canon[k]['name']} ({typ})")
            vecs = np.asarray(oll.embed(labels), dtype="float32")
            if not (vecs.ndim == 2 and vecs.shape[0] == len(keys)):
                _time.sleep(2.0)  # cold-start: embed model still loading — retry once
                vecs = np.asarray(oll.embed(labels), dtype="float32")
            if vecs.ndim == 2 and vecs.shape[0] == len(keys):
                norms = np.linalg.norm(vecs, axis=1, keepdims=True)
                norms[norms == 0] = 1.0
                vecs = vecs / norms
                sim = vecs @ vecs.T
                uf = _UF()
                for i in range(len(keys)):
                    for j in range(i + 1, len(keys)):
                        if sim[i, j] >= config.MERGE_COSINE_THRESHOLD:
                            a, b = canon[keys[i]]["name"].lower(), canon[keys[j]]["name"].lower()
                            if _fuzzy(a, b) >= 0.5 or a in b or b in a:
                                uf.union(keys[i], keys[j])
                groups: dict[str, list[str]] = defaultdict(list)
                for k in keys:
                    groups[uf.find(k)].append(k)
                merged: dict[str, dict] = {}
                for members in groups.values():
                    if len(members) == 1:
                        merged[members[0]] = canon[members[0]]
                        continue
                    members.sort(key=lambda k: -canon[k]["mentions"])
                    prim = canon[members[0]]
                    for m in members[1:]:
                        o = canon[m]
                        prim["type_votes"] += o["type_votes"]
                        prim["descs"] += o["descs"]
                        prim["sources"] += o["sources"]
                        prim["mentions"] += o["mentions"]
                        prim["aliases"].add(o["name"])
                        prim["aliases"] |= o["aliases"]
                        alias_index[m] = members[0]
                    merged[members[0]] = prim
                canon = merged
                if progress:
                    progress(f"merged to {len(canon)} entities")
        except Exception as e:  # pragma: no cover
            if progress:
                progress(f"embedding merge skipped: {e}")

    # ── Finalize nodes ──
    nodes: list[dict] = []
    keymap: dict[str, str] = {}
    used_ids: set[str] = set()
    for k, n in canon.items():
        tv = n["type_votes"]
        typ = tv.most_common(1)[0][0] if tv else "Concept"
        if typ == "Concept" and len(tv) > 1:
            for t, _ in tv.most_common():
                if t != "Concept":
                    typ = t
                    break
        typ = _refine_type(n["name"], typ)
        desc = n["descs"].most_common(1)[0][0] if n["descs"] else ""
        nid = (config.slugify(n["name"])[:48] or "n")
        base, i = nid, 2
        while nid in used_ids:
            nid = f"{base}-{i}"
            i += 1
        used_ids.add(nid)
        keymap[k] = nid
        nodes.append({
            "id": nid, "name": n["name"], "type": typ, "description": desc,
            "aliases": sorted({a for a in n["aliases"] if a})[:8],
            "sources": [f for f, _ in n["sources"].most_common(8)],
            "mentions": n["mentions"], "facts": [], "degree": 0,
        })

    def resolve_id(name: Any) -> str | None:
        k = _norm(name)
        seen: set[str] = set()
        while k in alias_index and k not in seen:
            seen.add(k)
            k = alias_index[k]
        return keymap.get(k)

    # ── Edges ──
    edge_map: dict[tuple, dict] = {}
    for r in rels:
        s = resolve_id(r.get("source", ""))
        t = resolve_id(r.get("target", ""))
        if not s or not t or s == t:
            continue
        rel_label = str(r.get("relation", "related to")).strip()[:40] or "related to"
        ek = (s, _norm(rel_label)[:40], t)
        e = edge_map.get(ek)
        if e is None:
            edge_map[ek] = {"source": s, "target": t, "relation": rel_label, "count": 0}
        edge_map[ek]["count"] += 1
    edges = list(edge_map.values())

    deg: Counter = Counter()
    for e in edges:
        deg[e["source"]] += 1
        deg[e["target"]] += 1
    nid_to_node = {n["id"]: n for n in nodes}
    for n in nodes:
        n["degree"] = deg.get(n["id"], 0)

    # ── Facts ──
    all_facts: list[dict] = []
    for f in facts:
        ids: list[str] = []
        for nm in f.get("entities", []):
            rid = resolve_id(nm)
            if rid:
                ids.append(rid)
        ids = list(dict.fromkeys(ids))
        all_facts.append({"text": f["text"], "nodes": ids, "file": (f.get("source") or {}).get("file")})
        for rid in ids[:4]:
            node = nid_to_node.get(rid)
            if node and len(node["facts"]) < 12 and f["text"] not in node["facts"]:
                node["facts"].append(f["text"])

    graph = {
        "project": project_id,
        "nodes": nodes,
        "edges": edges,
        "facts": all_facts,
        "stats": {"nodes": len(nodes), "edges": len(edges), "facts": len(all_facts),
                  "raw_entities": len(ents), "raw_relations": len(rels)},
        "generated": store.now_iso(),
    }
    store.save_graph(project_id, graph)
    return graph["stats"]
