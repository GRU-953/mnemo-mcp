# Changelog

All notable changes to **Mnemo** are documented here. Versioning is semver-ish
during 0.x.

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
