"""Fast smoke tests for the pure-logic parts of the pipeline (no Ollama needed).

Validates chunking, JSON salvage, entity resolution / graph build, digest, mind
map rendering, and neighborhood expansion using a synthetic extraction. Run:

    ./.venv/bin/python -m pytest tests/ -q
    ./.venv/bin/python tests/test_smoke.py        # also works standalone
"""
from __future__ import annotations

import os
import tempfile

# Point the store at a throwaway dir BEFORE touching store functions.
_TMP = tempfile.mkdtemp(prefix="mnemo-test-")
os.environ["MNEMO_HOME"] = _TMP

from mnemo.core import store, graph, digest, render, index, extract  # noqa: E402
from mnemo.core import ollama_client as oll  # noqa: E402

PROJECT = "test-proj"

SYNTHETIC = {
    "entities": [
        {"name": "Acme Corp", "type": "Organization", "description": "A manufacturer", "aliases": ["Acme"], "source": {"file": "a.md", "chunk": 0}},
        {"name": "Acme", "type": "Organization", "description": "Maker of widgets", "aliases": [], "source": {"file": "b.md", "chunk": 0}},
        {"name": "Jane Doe", "type": "Person", "description": "CEO of Acme", "aliases": [], "source": {"file": "a.md", "chunk": 0}},
        {"name": "Widget X", "type": "Product", "description": "Flagship product", "aliases": [], "source": {"file": "b.md", "chunk": 1}},
        {"name": "ISO 9001", "type": "Policy", "description": "Quality standard", "aliases": [], "source": {"file": "a.md", "chunk": 0}},
    ],
    "relations": [
        {"source": "Jane Doe", "relation": "leads", "target": "Acme Corp", "grounded": True, "src": {"file": "a.md", "chunk": 0}},
        {"source": "Acme", "relation": "makes", "target": "Widget X", "grounded": True, "src": {"file": "b.md", "chunk": 1}},
        {"source": "Acme Corp", "relation": "certified to", "target": "ISO 9001", "grounded": True, "src": {"file": "a.md", "chunk": 0}},
    ],
    "facts": [
        {"text": "Acme Corp is certified to ISO 9001.", "entities": ["Acme Corp", "ISO 9001"], "source": {"file": "a.md", "chunk": 0}},
        {"text": "Jane Doe is the CEO of Acme.", "entities": ["Jane Doe", "Acme"], "source": {"file": "a.md", "chunk": 0}},
        {"text": "Widget X is Acme's flagship product.", "entities": ["Widget X", "Acme"], "source": {"file": "b.md", "chunk": 1}},
    ],
}


def _seed():
    store.ensure_project(PROJECT)
    store.save_meta(PROJECT, {"name": "Test Project", "source_dir": "/tmp/docs"})
    store.write_json(store.project_dir(PROJECT) / "extractions.json", SYNTHETIC)


def test_chunking():
    text = "# H1\n" + ("word " * 50) + "\n# H2\n" + ("token " * 50)
    chunks = extract.chunk_markdown(text, words=40, overlap=5)
    assert len(chunks) >= 2, chunks
    assert all(c.strip() for c in chunks)


def test_json_salvage():
    assert oll.parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert oll.parse_json('garbage {"a": [1,2]} trailing')["a"] == [1, 2]
    assert oll.parse_json("not json at all") is None


def test_graph_merges_aliases():
    _seed()
    stats = graph.build_graph(PROJECT, embed=False)  # no Ollama
    g = store.load_graph(PROJECT)
    names = {n["name"] for n in g["nodes"]}
    # "Acme Corp" and "Acme" must collapse to ONE node via alias resolution.
    acme = [n for n in g["nodes"] if "acme" in n["name"].lower()]
    assert len(acme) == 1, f"Acme not merged: {[n['name'] for n in acme]}"
    assert acme[0]["mentions"] >= 2
    assert stats["nodes"] >= 3 and stats["edges"] >= 2
    # facts attached to nodes
    assert any(n["facts"] for n in g["nodes"])


def test_digest_compact():
    _seed()
    graph.build_graph(PROJECT, embed=False)
    res = digest.build_digest(PROJECT, llm_overview=False)
    md = store.memory_md_path(PROJECT).read_text(encoding="utf-8")
    assert "# Project Memory" in md
    assert "Acme" in md and "Widget X" in md
    assert res["approx_tokens"] < 1500, "digest should be compact"


def test_render_html():
    _seed()
    graph.build_graph(PROJECT, embed=False)
    res = render.build_mindmap(PROJECT)
    html = store.mindmap_path(PROJECT).read_text(encoding="utf-8")
    assert "cytoscape" in html.lower()
    assert "Acme Corp" in html
    assert "window.MNEMO" in html
    assert res["nodes"] >= 3


def test_expand():
    _seed()
    graph.build_graph(PROJECT, embed=False)
    res = index.expand(PROJECT, "Acme", depth=1)
    assert res["found"], res
    assert res["center"]["name"].lower().startswith("acme")
    assert len(res["relations"]) >= 1


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS {fn.__name__}")
            passed += 1
        except Exception as e:
            import traceback
            print(f"  FAIL {fn.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{passed}/{len(fns)} passed")
    return passed == len(fns)


if __name__ == "__main__":
    ok = _run_all()
    raise SystemExit(0 if ok else 1)
