# 🧠 Mnemo — local, token-free, graph-based project memory for Claude

[![CI](https://github.com/GRU-953/mnemo-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/GRU-953/mnemo-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Mnemo gives Claude durable **project memory** that is **created and queried almost
entirely by local, free, open-source models** — so it costs *near-zero Claude
tokens* to build *or* use. It turns a messy folder of documents (PDF, DOCX, PPTX,
XLSX, images, scans) into a **knowledge graph**, a compact **Markdown digest**, and
an **interactive HTML mind map** — and it is **reusable across projects**.

> **The idea:** Claude tokens are expensive; local compute is free. So every heavy
> step — document → text conversion, knowledge extraction, embeddings,
> visualization — runs on your machine. Claude only ever issues a tiny tool call
> and gets back compact metadata or a small, relevant subgraph — **never whole
> documents**.

```
 your documents ─► MarkItDown + Tesseract OCR + Ollama vision ─► Markdown   (local)
                                                                   │
                                   Ollama qwen2.5:7b  ── extract ──►  entities · relations · facts
                                                                   │
                              entity resolution (embeddings + fuzzy) ─► knowledge graph
                                                                   │
              ┌──────────────────────────────┬───────────────────┴───────────────────┐
              ▼                               ▼                                        ▼
        graph.json                       memory.md                              mindmap.html
     (source of truth)        (compact digest Claude reads)            (interactive Cytoscape graph)
              │
              ▼
   nomic-embed-text vectors ──► memory_query returns only a tiny relevant slice (not documents)
```

## Why it saves tokens

| | Traditional "read the files into context" | Mnemo |
|---|---|---|
| **Build** | N/A (or paste docs → 100k+ tokens) | one local tool call → compact stats (~tens of tokens) |
| **Use** | re-read documents every time | `memory_query` → a few hundred tokens of the *relevant* subgraph |
| **Where compute happens** | Claude (paid tokens) | your machine (free, local) |
| **Persistence** | none (per-conversation) | global store, reusable across sessions & projects |

**Measured on a real 62-file project** (PDFs, DOCX, PPTX, spreadsheets, scanned
images): the converted source text is **≈ 440,000 tokens**. Mnemo turns it into a
**≈ 1,000-token** `memory.md` digest (**~450× smaller**) plus a graph and mind map
— and the extraction itself runs on the local LLM, so the **Claude-token cost to
build is ≈ 0**. A typical `memory_query` answer is **~200 tokens**. Loading full
project context this way costs ~1k tokens instead of ~440k.

## What you get

- **Knowledge graph** (`graph.json`) — entities, typed relationships, atomic facts,
  each with provenance back to the source file.
- **Compact digest** (`memory.md`) — overview + key entities/relationships/facts,
  sized to a few hundred tokens; what Claude loads at session start.
- **Interactive mind map** (`mindmap.html`) — a self-contained Cytoscape.js graph:
  color-coded by type, searchable, click a node for its description, facts, and
  sources. Works offline.
- **Local retrieval** — semantic search over the graph via `nomic-embed-text`.

## Requirements

macOS or Linux, [Homebrew](https://brew.sh), and ~8 GB free disk for the models.
Everything else is installed for you. 16 GB RAM is comfortable for the default
`qwen2.5:7b` model (use `qwen2.5:3b` on smaller machines).

## Install

```bash
git clone https://github.com/GRU-953/mnemo-mcp
cd mnemo-mcp
./scripts/install.sh          # installs Ollama + Tesseract, pulls models, builds the venv
```

This installs/starts **Ollama**, pulls **qwen2.5:7b** (extraction),
**nomic-embed-text** (retrieval) and **moondream** (image captions), installs
**Tesseract** (OCR), and creates a Python 3.12 virtualenv with all dependencies.
Add `--with-audio` to also enable audio/video transcription (faster-whisper).

## Use it from the command line

```bash
./.venv/bin/python -m mnemo.cli status                       # check the stack
./.venv/bin/python -m mnemo.cli build --source "/path/to/docs"
./.venv/bin/python -m mnemo.cli overview                     # compact digest
./.venv/bin/python -m mnemo.cli query "what are the key risks?"
./.venv/bin/python -m mnemo.cli query "data governance" --scope all   # across all projects
./.venv/bin/python -m mnemo.cli expand "ADEX Group"
./.venv/bin/python -m mnemo.cli mindmap                      # open the HTML graph
```

## Use it from Claude (MCP plugin)

Once installed as a Claude Code plugin, Claude can call these tools (and the
`/memory`, `/memory-build`, `/memory-map`, `/memory-status` commands):

| Tool | Purpose |
|------|---------|
| `memory_build(source_dir, project?, …)` | Build/rebuild memory from a folder (local, token-free). |
| `memory_update(project?, source_dir?)` | Incremental refresh of changed files. |
| `memory_overview(project?)` | Compact digest — load at session start. |
| `memory_query(query, project?, k?, scope?)` | Semantic recall → tiny relevant subgraph. |
| `memory_expand(entity, project?, depth?)` | One entity's neighborhood. |
| `memory_list_projects()` | All projects + counts. |
| `memory_open_mindmap(project?)` | Open the interactive graph. |
| `memory_status()` | Stack health. |

### Install the plugin

From a local clone, add it as a marketplace and install:

```bash
claude plugin marketplace add /absolute/path/to/mnemo-mcp
claude plugin install mnemo@mnemo
```

(or use `/plugin` inside Claude Code). The MCP server is launched from the plugin's
own virtualenv via `.mcp.json`.

## Reusable across projects

Memory lives in a global store (`~/.claude-memory/`, override with `MNEMO_HOME`)
namespaced per project. `memory_query(..., scope="all")` searches every project at
once, so knowledge built for one project is available to others. Copy a
`~/.claude-memory/projects/<id>/` folder to move a project's memory to another
machine.

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `MNEMO_HOME` | `~/.claude-memory` | store location |
| `MNEMO_EXTRACT_MODEL` | `qwen2.5:7b` | extraction LLM (Ollama) |
| `MNEMO_EMBED_MODEL` | `nomic-embed-text` | embedding model |
| `MNEMO_VISION_MODEL` | `moondream` | image-caption model |
| `MNEMO_OCR_LANG` | `eng` | Tesseract languages, e.g. `eng+ben` |
| `MNEMO_CHUNK_WORDS` | `1400` | extraction chunk size |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama endpoint |

## Privacy

Mnemo is **100% local**. Converted text, the graph, the digest, and the mind map
are written only to `~/.claude-memory/`. Nothing is sent to any cloud service, and
**none of your documents or extracted memory is part of this repository** (the
store is outside the repo and git-ignored).

## Robust, resumable builds

Extraction checkpoints after every document. If a build is interrupted (or Ollama
hiccups), just re-run `memory_build` / `memory_update` for the same project — it
**resumes** from where it stopped instead of restarting, and never marks a document
"done" if its extraction errored. This keeps large corpora practical on a laptop.

## How it works (pipeline)

1. **Ingest** — `MarkItDown` converts each file; images and scanned PDFs are OCR'd
   with Tesseract and captioned with a local vision model; a hash manifest enables
   incremental updates; identical content (e.g. a DOCX and its PDF) is de-duplicated.
2. **Extract** — each document is chunked and sent to a local LLM with a strict,
   compact JSON schema → entities (typed), relations, and atomic facts.
3. **Resolve** — duplicate entities are merged (exact name, alias, then embedding +
   fuzzy similarity) into canonical nodes with provenance and centrality.
4. **Digest / Index / Render** — a compact `memory.md`, an embedding index for
   retrieval, and a self-contained interactive `mindmap.html`.

## License

MIT — see [LICENSE](LICENSE). Bundles [Cytoscape.js](https://js.cytoscape.org/)
(MIT) and uses [MarkItDown](https://github.com/microsoft/markitdown) (MIT),
[Ollama](https://ollama.com), and [Tesseract](https://github.com/tesseract-ocr/tesseract).
