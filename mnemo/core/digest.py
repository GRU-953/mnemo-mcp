"""Digest: render the graph into a compact, token-efficient memory.md.

This is the artifact Claude reads at session start (`memory_overview`). It is
deliberately small (target < ~1.5k tokens): an overview, the highest-centrality
entities by type, key relationships, and key facts — not raw documents.
"""
from __future__ import annotations

from collections import defaultdict

from . import config, store
from . import ollama_client as oll

MAX_ENTITIES = 30
MAX_PER_TYPE = 6
MAX_RELATIONS = 14
MAX_FACTS = 12


def _score(n: dict) -> int:
    return n.get("degree", 0) * 2 + n.get("mentions", 0)


def _overview_llm(project: str, top_nodes: list[dict], top_facts: list[str], model: str | None) -> str:
    model = model or config.EXTRACT_MODEL
    ents = "; ".join(f"{n['name']} [{n['type']}]" for n in top_nodes[:20])
    fcts = "\n".join(f"- {f}" for f in top_facts[:10])
    prompt = (
        f"Write a concise 4-6 sentence overview of the project for a teammate's memory. "
        f"Use ONLY the entities and facts below. Be specific and factual. No preamble, no bullet points.\n\n"
        f"KEY ENTITIES: {ents}\n\nKEY FACTS:\n{fcts}\n\nOVERVIEW:"
    )
    try:
        return oll.generate(prompt, model=model, temperature=0.2, num_ctx=4096, timeout=180).strip()
    except Exception:
        return ""


def build_digest(project_id: str, *, llm_overview: bool = True, model: str | None = None) -> dict:
    g = store.load_graph(project_id)
    nodes = g.get("nodes", [])
    edges = g.get("edges", [])
    facts = g.get("facts", [])
    meta = store.load_meta(project_id)
    nid = {n["id"]: n for n in nodes}

    ranked = sorted(nodes, key=lambda n: -_score(n))

    def fact_score(f: dict) -> int:
        return sum(_score(nid[i]) for i in f.get("nodes", []) if i in nid) + 1

    seen: set[str] = set()
    top_facts: list[str] = []
    for f in sorted((f for f in facts if f.get("text")), key=lambda f: -fact_score(f)):
        t = f["text"].strip()
        if t.lower() in seen:
            continue
        seen.add(t.lower())
        top_facts.append(t)
        if len(top_facts) >= 40:
            break

    topset = {n["id"] for n in ranked[:40]}
    rel_ranked = sorted(
        edges,
        key=lambda e: -(e.get("count", 1) + (2 if e["source"] in topset and e["target"] in topset else 0)),
    )

    overview = ""
    if llm_overview and oll.ping():
        overview = _overview_llm(project_id, ranked, top_facts, model)
    if not overview:
        lead = [n for n in ranked if n["type"] in ("Project", "Organization")][:2]
        bits = [f"{n['name']} — {n['description']}" for n in lead if n.get("description")]
        overview = " ".join(bits) or (
            f"Project memory with {len(nodes)} entities and {len(edges)} relationships."
        )

    md: list[str] = []
    md.append(f"# Project Memory — {meta.get('name', project_id)}")
    md.append("")
    md.append(
        f"*{len(nodes)} entities · {len(edges)} relationships · {len(facts)} facts · "
        f"generated {g.get('generated', '')}*"
    )
    if meta.get("source_dir"):
        md.append(f"*Source: {meta['source_dir']}*")
    md.append("")
    md.append("## Overview")
    md.append("")
    md.append(overview)
    md.append("")

    md.append("## Key entities")
    md.append("")
    by_type: dict[str, list[dict]] = defaultdict(list)
    for n in ranked:
        by_type[n["type"]].append(n)
    type_order = sorted(by_type, key=lambda t: -sum(_score(n) for n in by_type[t]))
    total = 0
    for t in type_order:
        if total >= MAX_ENTITIES:
            break
        items = by_type[t][:MAX_PER_TYPE]
        if not items:
            continue
        md.append(f"**{t}**")
        for n in items:
            if total >= MAX_ENTITIES:
                break
            d = f" — {n['description']}" if n.get("description") else ""
            md.append(f"- {n['name']}{d}")
            total += 1
        md.append("")

    md.append("## Key relationships")
    md.append("")
    for e in rel_ranked[:MAX_RELATIONS]:
        s = nid.get(e["source"], {}).get("name", e["source"])
        t = nid.get(e["target"], {}).get("name", e["target"])
        md.append(f"- {s} **{e['relation']}** {t}")
    md.append("")

    md.append("## Key facts")
    md.append("")
    for t in top_facts[:MAX_FACTS]:
        md.append(f"- {t}")
    md.append("")
    md.append("---")
    md.append("*Compact memory digest. Query `memory_query` for specifics, "
              "`memory_expand` to explore an entity, or open the visual mind map.*")

    text = "\n".join(md)
    store.write_text(store.memory_md_path(project_id), text)
    return {"chars": len(text), "approx_tokens": len(text) // 4,
            "path": str(store.memory_md_path(project_id))}
