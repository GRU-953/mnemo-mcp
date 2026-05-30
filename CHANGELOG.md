# Changelog

All notable changes to **Mnemo** are documented here. Versioning is semver-ish
during 0.x.

## [0.7.0] — Extraction quality
### Changed
- Deterministic entity-type refinement (a year/range -> Milestone, a number/percentage
  -> Metric) and filtering of sentence-like / vision-caption fragments mistaken for
  entity names. Sharper extraction prompt: names are short noun phrases; explicit type hints.
### Fixed
- Entity-merge was being skipped right after an on-demand Ollama cold start (the
  `has_model` gate can be empty momentarily), producing under-merged graphs on the
  first build of a session. Now uses `ensure_up` + an embed retry.

## [0.6.0] — Portable memory export
### Added
- `memory_export` MCP tool + `mnemo export --to <dir>` — copy a project's memory
  out of the global store for reuse in any other chat/project: memory.md (optionally
  named `CLAUDE.md`), plus optional graph.json / mindmap.html. Makes memory reusable
  in Claude Desktop project knowledge or other repos without the MCP.

## [0.5.0] — On-demand local LLM
### Added
- **On-demand Ollama lifecycle** (Apple-silicon memory): the local LLM starts only
  when a task needs it and stops after `MNEMO_OLLAMA_IDLE` (default 300s) of
  inactivity. A detached watchdog stops a *Mnemo-started* server (never a
  brew/user-launched one), and models unload via an idle-aligned keep-alive, so
  idle RAM drops to ~0. `install.sh` disables the always-on service. State is shown
  in `mnemo status`; tune via `MNEMO_OLLAMA_IDLE` / disable via `MNEMO_OLLAMA_LIFECYCLE=off`.

## [0.4.0]
### Added
- `memory_stats` MCP tool + `mnemo stats` — graph analytics (entity/relationship/fact
  counts, entities-by-type, most-central entities).
- Memory-adaptive extraction context window: sizes `num_ctx` to detected unified
  memory (4096 ≤8 GB / 8192 ≤16 GB / 16384 above) unless `MNEMO_NUM_CTX` is set.
- Full-pipeline integration test (ingest→extract→graph→digest→index→query, mocked LLM).
### Fixed
- `memory_query(scope="all")` no longer crashes when projects have indexes of
  different embedding dimensions (e.g. different embed models) — mismatched indexes
  are skipped.

## [0.3.1]
### Added
- Expanded test coverage to 20 (pipeline health, empty-graph digest, store round-trip, updater version compare).
- README table of contents; professional repo description + topics on GitHub.

## [0.3.0] — Self-update
### Added
- **Stay on the latest release**: `mnemo check-update`, `mnemo self-update`, and the
  `memory_self_update` MCP tool — a fast-forward `git pull` of the plugin checkout
  + reinstall (never discards local changes; ff-only). On server start
  `MNEMO_AUTO_UPDATE` controls behavior: `check` (default — only notifies if an
  update exists), `auto` (apply automatically), `off`.

## [0.2.0] — Apple-silicon optimization
### Added
- **Parallel ingestion** across CPU cores (auto-sized worker pool) — much faster
  document conversion / OCR on multi-core Macs.
- **Ollama Metal/memory tuning** applied by `install.sh`: `OLLAMA_FLASH_ATTENTION`,
  `OLLAMA_KV_CACHE_TYPE=q8_0` (~halves context-cache memory), `OLLAMA_MAX_LOADED_MODELS=1`
  (keeps the 7B model resident on 16 GB and prevents extract/embed/vision model
  thrashing), `OLLAMA_NUM_PARALLEL=1`.
- **Hardware auto-detection**: `mnemo status` now reports chip, performance/efficiency
  cores, RAM, the Metal GPU, ingest worker count, and recommended Ollama tuning.

## [0.1.8]
### Added
- Format-variant de-duplication: documents sharing a name stem in different
  formats (e.g. a `.docx` and its `.pdf` export) are detected by stem + a size
  guard and extracted once — cleaner graph and faster builds.

## [0.1.7]
### Fixed
- Sync `__version__` (was stale at 0.1.0) and add `mnemo --version`.
### Added
- CI status badge in the README.

## [0.1.6]
### Fixed
- Mind map: harden the embedded graph JSON against HTML injection — escape
  `<`, `>`, `&`, and U+2028/U+2029, and HTML-escape the title — so entity names
  from arbitrary documents (e.g. containing `</script>`) can't break out of the
  data `<script>` tag. Added a regression test.

## [0.1.5]
### Added
- Mind map: a layout switcher (force / concentric / tree / circle / grid) and
  per-type entity counts in the legend, for easier exploration of larger graphs.

## [0.1.4]
### Added
- `pyproject.toml` with a `mnemo` console script (`pip install -e .` → run `mnemo …`).
- Expanded offline test suite: retrieval (`memory_query`/`memory_expand`),
  cross-project `memory_link` + `scope="all"`, `slugify`, and source-file filtering.
### Changed
- Dropped the unused `pytesseract` dependency (OCR uses the system `tesseract`
  binary via subprocess); `install.sh` now also installs the package for the CLI.

## [0.1.3]
### Fixed
- Resilient extraction: retry transient Ollama errors, never mark a document
  "done" if its chunks errored, and abort after sustained errors instead of
  silently producing empty memory.
- Roll back a document's partial results when it errors part-way, so a resume
  re-extracts it cleanly with no duplicated entities/facts.
### Added
- GitHub Actions CI running the offline smoke tests on every push/PR.

## [0.1.2]
### Added
- Resumable extraction: per-document checkpoint (`done_files`) so large or
  interrupted builds continue instead of restarting.
### Changed
- Strip HTML comments before extraction and filter provenance/OCR junk entities
  (e.g. `mnemo-source`) out of the graph.

## [0.1.1]
### Added
- Cross-project reuse: `memory_link` tool + `reuse` module.

## [0.1.0]
### Added
- Initial release: local, token-free, graph-based project memory for Claude.
  Document → Markdown (MarkItDown + Tesseract OCR + Ollama vision) → local-LLM
  knowledge graph → compact `memory.md` digest + embedding index + interactive
  Cytoscape mind map. MCP server with 9 tools, slash commands, skill, and an
  auto-installer. Reusable across projects via a global store.
