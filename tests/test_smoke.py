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


def test_partial_error_rollback():
    """A document whose chunks error part-way must leave NO partial entities and
    must not be marked done (so resume re-extracts it cleanly)."""
    from mnemo.core import extract as ex
    proj = "rollback-proj"
    sd = store.project_dir(proj) / "sources"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "a.md").write_text("# A\n" + ("alpha " * 60), encoding="utf-8")
    (sd / "b.md").write_text("# B\n" + ("beta " * 3000), encoding="utf-8")  # -> multiple chunks

    real = ex.extract_chunk
    state = {"b_chunk": 0}

    def fake(text, *, model=None, source=None):
        f = (source or {}).get("file", "")
        if f == "a.md":
            return {"entities": [{"name": "Alpha", "type": "Concept", "description": "", "aliases": [], "source": source}], "relations": [], "facts": []}
        if f == "b.md":
            state["b_chunk"] += 1
            if state["b_chunk"] == 1:  # first chunk succeeds...
                return {"entities": [{"name": "BetaPartial", "type": "Concept", "description": "", "aliases": [], "source": source}], "relations": [], "facts": []}
            return {"entities": [], "relations": [], "facts": [], "error": "simulated outage"}  # ...then errors
        return {"entities": [], "relations": [], "facts": []}

    ex.extract_chunk = fake
    try:
        ex.extract_project(proj, resume=False)
    finally:
        ex.extract_chunk = real

    d = store.read_json(store.project_dir(proj) / "extractions.json")
    names = {e["name"] for e in d["entities"]}
    done = set(d.get("done_files", []))
    assert "Alpha" in names, names
    assert "BetaPartial" not in names, "partial results from an errored doc must be rolled back"
    assert "a.md" in done and "b.md" not in done, f"errored doc must not be marked done: {done}"


_VOCAB = ["esg", "risk", "employee", "policy", "audit", "carbon", "energy", "data", "vendor", "quality"]


def _install_ollama_mock():
    """Deterministic bag-of-words embeddings so retrieval is testable offline."""
    from mnemo.core import ollama_client as oll

    def mock_embed(texts, model=None, timeout=180.0):
        out = []
        for t in texts:
            tl = str(t).lower()
            v = [float(tl.count(w)) for w in _VOCAB]
            if sum(v) == 0:
                v[0] = 1e-3
            out.append(v)
        return out

    oll.embed = mock_embed
    oll.ping = lambda timeout=2.0: True
    oll.has_model = lambda name: True


def test_slugify():
    from mnemo.core import config
    assert config.slugify("Hello World!") == "hello-world"
    assert config.slugify("  ADEX  Group  ") == "adex-group"
    assert config.slugify("") == "untitled"


def test_ingest_file_iteration():
    import os
    import tempfile
    from mnemo.core import ingest
    d = tempfile.mkdtemp(prefix="mnemo-ingest-")
    for name in ("real.txt", "deck.pptx", "link.gdoc", ".DS_Store", "._resfork", "sheet.gsheet"):
        with open(os.path.join(d, name), "w") as f:
            f.write("x")
    names = {p.name for p in ingest.iter_source_files(d)}
    assert "real.txt" in names and "deck.pptx" in names
    assert "link.gdoc" not in names and "sheet.gsheet" not in names  # pointer stubs skipped
    assert ".DS_Store" not in names and "._resfork" not in names      # junk skipped


def test_query_and_expand_offline():
    from mnemo.core import graph, index
    _install_ollama_mock()
    proj = "query-proj"
    store.ensure_project(proj)
    store.write_json(store.project_dir(proj) / "extractions.json", {
        "entities": [
            {"name": "ESG Risk Register", "type": "Issue", "description": "tracks esg risk", "aliases": [], "source": {"file": "x", "chunk": 0}},
            {"name": "Employee Policy", "type": "Policy", "description": "employee policy rules", "aliases": [], "source": {"file": "x", "chunk": 0}},
        ],
        "relations": [{"source": "Employee Policy", "relation": "mitigates", "target": "ESG Risk Register", "src": {"file": "x", "chunk": 0}}],
        "facts": [{"text": "The ESG risk register lists carbon risk.", "entities": ["ESG Risk Register"], "source": {"file": "x", "chunk": 0}}],
    })
    graph.build_graph(proj, embed=False)
    assert index.build_index(proj)["vectors"] > 0
    res = index.query("esg risk", project_id=proj, k=2)
    assert res["nodes"], res
    assert any("esg" in n["name"].lower() for n in res["nodes"]), res
    ex = index.expand(proj, "ESG Risk Register")
    assert ex["found"] and ex["center"]["name"] == "ESG Risk Register"


def test_reuse_link_offline():
    from mnemo.core import graph, index, reuse
    _install_ollama_mock()
    store.ensure_project("src-proj")
    store.write_json(store.project_dir("src-proj") / "extractions.json", {
        "entities": [{"name": "Carbon Credits", "type": "Concept", "description": "carbon energy credits", "aliases": [], "source": {"file": "s", "chunk": 0}}],
        "relations": [], "facts": [{"text": "Carbon credits monetize energy.", "entities": ["Carbon Credits"], "source": {"file": "s", "chunk": 0}}],
    })
    graph.build_graph("src-proj", embed=False)
    index.build_index("src-proj")
    store.ensure_project("dst-proj")
    store.write_json(store.project_dir("dst-proj") / "extractions.json", {
        "entities": [{"name": "Vendor Audit", "type": "Process", "description": "vendor audit", "aliases": [], "source": {"file": "d", "chunk": 0}}],
        "relations": [], "facts": [],
    })
    graph.build_graph("dst-proj", embed=False)
    index.build_index("dst-proj")
    r = reuse.link_projects("dst-proj", "src-proj", query=None, k=5)
    assert r["linked"] >= 1, r
    g = store.load_graph("dst-proj")
    assert any(n.get("from_project") == "src-proj" for n in g["nodes"]), "imported nodes must be tagged"
    # cross-project scope=all returns results from both projects
    res = index.query("carbon energy", scope="all", k=5)
    assert res["nodes"], res


def test_mindmap_html_injection_safe():
    """An entity name containing '</script>' must not break out of the data
    <script> tag in the rendered mind map."""
    from mnemo.core import graph, render
    proj = "xss-proj"
    store.ensure_project(proj)
    payload = "Evil </script><script>alert(1)</script>"
    store.write_json(store.project_dir(proj) / "extractions.json", {
        "entities": [{"name": payload, "type": "Concept", "description": "x", "aliases": [], "source": {"file": "x", "chunk": 0}}],
        "relations": [], "facts": [],
    })
    graph.build_graph(proj, embed=False)
    render.build_mindmap(proj)
    html = store.mindmap_path(proj).read_text(encoding="utf-8")
    assert "window.MNEMO" in html
    assert "<script>alert(1)</script>" not in html, "payload broke out of the data script!"
    assert "\\u003c/script\\u003e" in html, "expected escaped </script> in embedded data"


def test_format_variant_dedup():
    """Same-name documents in different formats (e.g. report.docx + report.pdf)
    should be de-duplicated by stem so the graph isn't doubled."""
    from mnemo.core import extract as ex
    proj = "dedup-proj"
    sd = store.project_dir(proj) / "sources"
    sd.mkdir(parents=True, exist_ok=True)
    body = "# Report\n" + ("the quick brown fox jumps over the lazy dog " * 60)
    (sd / "report.docx.md").write_text(body, encoding="utf-8")
    (sd / "report.pdf.md").write_text(body + " minor extraction difference", encoding="utf-8")
    (sd / "other.txt.md").write_text("# Other\n" + ("alpha beta gamma delta " * 60), encoding="utf-8")
    real = ex.extract_chunk
    ex.extract_chunk = lambda text, *, model=None, source=None: {
        "entities": [{"name": "E", "type": "Concept", "description": "", "aliases": [], "source": source}],
        "relations": [], "facts": []}
    try:
        ex.extract_project(proj, resume=False)
    finally:
        ex.extract_chunk = real
    done = set(store.read_json(store.project_dir(proj) / "extractions.json").get("done_files", []))
    assert "report.docx.md" in done
    assert "report.pdf.md" not in done, "same-stem format variant should be skipped"
    assert "other.txt.md" in done


def test_platform_tuning():
    from mnemo.core import platform_tuning as pt
    hw = pt.hardware_info()
    assert {"os", "arch", "cpu_count", "apple_silicon"} <= set(hw)
    assert isinstance(hw["apple_silicon"], bool)
    assert pt.recommended_num_ctx(8) == 4096
    assert pt.recommended_num_ctx(16) == 8192
    assert pt.recommended_num_ctx(None) == 8192
    st = pt.ollama_tuning_status()
    assert "OLLAMA_FLASH_ATTENTION" in st["recommended"]
    assert "OLLAMA_KV_CACHE_TYPE" in st["recommended"]


def test_parallel_ingest():
    import os
    import tempfile
    from mnemo.core import ingest as ing
    d = tempfile.mkdtemp(prefix="mnemo-par-")
    for i in range(6):
        with open(os.path.join(d, f"f{i}.txt"), "w") as f:
            f.write("content " + str(i))
    real = ing.convert_file
    ing.convert_file = lambda p, **o: {"markdown": f"# {os.path.basename(str(p))}\n\nbody {p}", "method": "mock", "chars": 30}
    try:
        r = ing.ingest_dir(d, "par-proj", incremental=False, workers=4)
    finally:
        ing.convert_file = real
    assert r["total"] == 6 and r["converted"] == 6, r
    assert r["workers"] == 4
    mds = list((store.project_dir("par-proj") / "sources").rglob("*.md"))
    assert len(mds) == 6, f"expected 6 md outputs, got {len(mds)}"


def test_updater_logic():
    from mnemo.core import updater as up
    assert up._ver_key("v0.2.0") < up._ver_key("0.3.0")
    assert up._ver_key("0.10.0") > up._ver_key("0.9.9")
    assert up._ver_key("v1.0.0") == up._ver_key("1.0.0")
    cv = up.current_version()
    assert isinstance(cv, str) and cv[0].isdigit()
    assert "/" in up.repo_slug()


def test_updater_version_compare():
    from mnemo.core import updater as up
    assert up._ver_key("v0.2.0") < up._ver_key("0.3.0")
    assert up._ver_key("0.1.10") > up._ver_key("0.1.2")
    assert up.current_version() == up.current_version()  # stable
    real = up.latest_release
    try:
        up.latest_release = lambda timeout=8.0: {"tag": "v9.9.9", "name": "x", "url": "u"}
        r = up.check_update()
        assert r["available"] is True and r["latest"] == "9.9.9"
        up.latest_release = lambda timeout=8.0: {"tag": "v0.0.1"}
        assert up.check_update()["available"] is False
        up.latest_release = lambda timeout=8.0: None
        assert up.check_update()["available"] is False
    finally:
        up.latest_release = real


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
