---
description: Check the local memory stack (Ollama, models, Tesseract) and list projects
argument-hint: ""
---

# Memory status

Check that the local memory stack is healthy and list existing projects.

## Instructions

1. Call `memory_status`.
2. Summarize for the user:
   - Is Ollama running, and are the extraction / embedding / vision models present?
   - Is Tesseract (OCR) available?
   - Where is the memory store, and which projects exist (with entity/edge counts)?
3. If anything is missing, tell the user to run `scripts/install.sh` (it installs
   Ollama, pulls models, sets up the venv) — all local and free.
