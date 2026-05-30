# Connectors / local services

Mnemo is **fully local** — it does not connect to any cloud API. Its "connectors"
are local programs the installer sets up:

| Service | Role | Installed by |
|---|---|---|
| **Ollama** (`localhost:11434`) | Local LLM server: extraction (`qwen2.5:7b`), embeddings (`nomic-embed-text`), image captions (`moondream`) | `brew install ollama` + `ollama pull …` |
| **Tesseract** | OCR for images and scanned PDFs | `brew install tesseract` |
| **MarkItDown** (Python lib) | Document → Markdown conversion (PDF/DOCX/PPTX/XLSX) | `pip install` (in the venv) |
| **faster-whisper** (optional) | Audio/video transcription | `./scripts/install.sh --with-audio` |

The MCP server (`mnemo`) is declared in [`.mcp.json`](.mcp.json) and launched from
the plugin's own virtualenv (`${CLAUDE_PLUGIN_ROOT}/.venv/bin/python -m mnemo.server`).

No API keys. No network calls. All data stays in `~/.claude-memory/`.
