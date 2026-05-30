#!/usr/bin/env bash
# Mnemo installer — sets up the entire local, free/open-source stack.
#   - Homebrew (checked), Tesseract OCR, Ollama (+ models)
#   - a Python 3.12 venv with all dependencies
#   - vendored Cytoscape.js for the offline mind map
#
# Usage:
#   ./scripts/install.sh                 # full install
#   ./scripts/install.sh --with-audio    # also install faster-whisper (audio/video)
#   ./scripts/install.sh --no-models     # skip pulling Ollama models
#   MNEMO_MODELS="qwen2.5:3b nomic-embed-text moondream" ./scripts/install.sh
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

WITH_AUDIO=0
PULL_MODELS=1
for a in "$@"; do
  case "$a" in
    --with-audio) WITH_AUDIO=1 ;;
    --no-models)  PULL_MODELS=0 ;;
  esac
done

MODELS="${MNEMO_MODELS:-qwen2.5:7b nomic-embed-text moondream}"
say(){ printf "\033[1;36m[mnemo]\033[0m %s\n" "$*"; }
warn(){ printf "\033[1;33m[mnemo] warning:\033[0m %s\n" "$*"; }

# ── 1. Homebrew ───────────────────────────────────────────────────────────
if ! command -v brew >/dev/null 2>&1; then
  warn "Homebrew not found. Install it from https://brew.sh then re-run."
  exit 1
fi

# ── 2. Tesseract OCR ──────────────────────────────────────────────────────
if ! command -v tesseract >/dev/null 2>&1; then
  say "installing Tesseract OCR…"
  brew install tesseract || warn "tesseract install failed (OCR will be unavailable)"
else
  say "Tesseract present: $(tesseract --version 2>&1 | head -1)"
fi

# ── 3. Ollama (local LLM server) ──────────────────────────────────────────
if ! command -v ollama >/dev/null 2>&1; then
  say "installing Ollama…"
  brew install ollama || { warn "ollama install failed"; }
fi
if ! curl -sf http://localhost:11434/api/version >/dev/null 2>&1; then
  say "starting Ollama…"
  brew services start ollama >/dev/null 2>&1 || (nohup ollama serve >/tmp/ollama-serve.log 2>&1 & disown)
  for i in $(seq 1 60); do curl -sf http://localhost:11434/api/version >/dev/null 2>&1 && break; sleep 1; done
fi
curl -sf http://localhost:11434/api/version >/dev/null 2>&1 && say "Ollama up: $(curl -s http://localhost:11434/api/version)" || warn "Ollama not reachable"

# ── 4. Models ─────────────────────────────────────────────────────────────
if [ "$PULL_MODELS" = "1" ]; then
  for m in $MODELS; do
    if ollama list 2>/dev/null | awk '{print $1}' | grep -q "^${m%%:*}"; then
      say "model present: $m"
    else
      say "pulling model: $m (one-time download)…"
      ollama pull "$m" || warn "failed to pull $m"
    fi
  done
fi

# ── 5. Python venv + dependencies ─────────────────────────────────────────
PY=""
for c in python3.12 python3.11 python3.13 python3; do
  command -v "$c" >/dev/null 2>&1 && { PY="$c"; break; }
done
[ -z "$PY" ] && { warn "no python3 found"; exit 1; }
say "creating venv with $($PY --version 2>&1)…"
"$PY" -m venv .venv || { warn "venv creation failed"; exit 1; }
./.venv/bin/python -m pip install --quiet --upgrade pip wheel setuptools
say "installing Python dependencies…"
./.venv/bin/python -m pip install --quiet -r requirements.txt || { warn "pip install failed"; exit 1; }
if [ "$WITH_AUDIO" = "1" ]; then
  say "installing faster-whisper (audio/video transcription)…"
  ./.venv/bin/python -m pip install --quiet "faster-whisper>=1.0.0" || warn "faster-whisper install failed"
fi

# ── 6. Vendored Cytoscape.js (offline mind map) ───────────────────────────
if [ ! -s assets/cytoscape.min.js ]; then
  say "fetching Cytoscape.js…"
  mkdir -p assets
  curl -fsSL "https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.30.2/cytoscape.min.js" \
    -o assets/cytoscape.min.js || warn "cytoscape download failed (HTML will use CDN fallback)"
fi

# ── 7. Health check ───────────────────────────────────────────────────────
say "verifying…"
./.venv/bin/python -m mnemo.cli status || true

printf "\n\033[1;32m[mnemo] install complete.\033[0m\n"
cat <<'EOF'
Try it:
  ./.venv/bin/python -m mnemo.cli build --source "/path/to/your/docs"
  ./.venv/bin/python -m mnemo.cli overview
  ./.venv/bin/python -m mnemo.cli query "your question"
  ./.venv/bin/python -m mnemo.cli mindmap

Inside Claude Code, the MCP tools (memory_build, memory_query, …) are available
once this plugin is installed. See README.md.
EOF
