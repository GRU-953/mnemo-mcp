---
name: memory
description: >
  Local, token-free, graph-based project memory. Use this skill whenever the user
  wants to remember, recall, or build durable context about a project, codebase,
  client, or document set — e.g. "remember this project", "build memory from these
  files", "what do we know about X", "recall our decisions on Y", "give me the
  project overview", "set up project memory", or when starting work on a project
  that already has memory. Memory is created and queried entirely by LOCAL models
  (Ollama + Tesseract + MarkItDown), so it costs almost no Claude tokens. Prefer
  this over reading whole documents into context. Not for one-off web research.
---

# Mnemo — local graph memory

Mnemo gives Claude durable **project memory** built and queried **entirely
locally** (Ollama for the LLM + embeddings, Tesseract for OCR, MarkItDown for
document conversion). The guiding principle:

> **Claude tokens are precious; local compute is free.** Never load whole
> documents into the conversation when a `memory_query` returns the same answer in
> a few hundred tokens.

Everything is stored in a global store (`~/.claude-memory/`, override with
`MNEMO_HOME`) namespaced per project, so memory **persists across sessions and is
reusable across projects**.

## When to use which tool

- **Starting work on a project** → `memory_overview` (loads a compact digest:
  overview + key entities/relationships/facts; a few hundred tokens).
- **Need a specific answer** → `memory_query(query, scope="project"|"all")`.
  Returns only the most relevant entities + facts with provenance. Use
  `scope="all"` to draw on every project's memory at once.
- **Drill into one thing** → `memory_expand(entity)` for its neighborhood.
- **Create memory from documents** → `memory_build(source_dir)`. Converts every
  file (PDF/DOCX/PPTX/XLSX/images via OCR + a local vision model), extracts a
  knowledge graph, writes `memory.md` + an embedding index + an interactive HTML
  mind map. Returns compact stats only. Runs for minutes on large corpora — all
  local; do not read the files yourself.
- **Refresh after files change** → `memory_update` (incremental; only changed
  files are re-processed).
- **See the graph** → `memory_open_mindmap`.
- **Health / inventory** → `memory_status`, `memory_list_projects`.

## Token discipline (important)

1. At the start of project work, call `memory_overview` once instead of opening
   files.
2. For questions, call `memory_query` first. Only read a specific source file if
   memory is genuinely insufficient — and then read just that one file.
3. When building/updating memory, rely on the tool's compact return value; never
   echo document contents into the chat.
4. The build and query operations themselves run on the local LLM — they do not
   consume Claude tokens for the heavy lifting.

## Setup

If `memory_status` shows Ollama down or models missing, run the installer
(one-time, local, free):

```
./scripts/install.sh
```

It installs Ollama + Tesseract, pulls `qwen2.5:7b` (extraction),
`nomic-embed-text` (retrieval), and `moondream` (image captions), and creates the
Python environment. Models are configurable via `MNEMO_EXTRACT_MODEL`,
`MNEMO_EMBED_MODEL`, `MNEMO_VISION_MODEL`.

## Tools

| Tool | Purpose |
|------|---------|
| `memory_build(source_dir, project?, model?, vision?, ocr_lang?, max_files?, reset?)` | Build/rebuild memory from a folder (local, token-free). |
| `memory_update(project?, source_dir?)` | Incremental refresh of changed files. |
| `memory_overview(project?)` | Compact project digest (best at session start). |
| `memory_query(query, project?, k?, scope?)` | Semantic recall → tiny relevant subgraph. |
| `memory_expand(entity, project?, depth?)` | One entity's neighborhood. |
| `memory_list_projects()` | All projects + counts. |
| `memory_open_mindmap(project?)` | Open the interactive HTML graph. |
| `memory_status()` | Stack health (Ollama, models, Tesseract, store). |

## Privacy

Converted text, the graph, and the mind map live only in `~/.claude-memory/` on the
local machine. Nothing is sent to the cloud and nothing about your documents is
committed to the plugin's repository.
