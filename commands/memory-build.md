---
description: Build or refresh local project memory from a folder of documents (token-free)
argument-hint: "[path-to-folder] [optional: project name]"
---

# Build project memory

Build a local, token-free knowledge graph + mind map from a folder of documents.
All work (conversion, OCR, vision, LLM extraction, embeddings) runs locally — this
costs almost no Claude tokens.

## Instructions

1. Determine the source folder from the user's message (`$ARGUMENTS`). If none is
   given, ask which folder to ingest (an absolute path).
2. First call `memory_status` to confirm Ollama is running and the models are
   present. If not, tell the user to run `scripts/install.sh`.
3. Call `memory_build` with `source_dir` (and `project` if the user named one).
   - This may take several minutes for large corpora. That is expected — it is
     entirely local. Do **not** read the documents yourself.
4. Report the compact result: number of files ingested, entities/edges in the
   graph, the `memory.md` token size, and the mind-map path.
5. Offer next steps: `memory_overview` to load context, `memory_query` to search,
   or `memory_open_mindmap` to view the graph.

If the project already exists, prefer `memory_update` (incremental) unless the user
asks for a full rebuild (`reset`).
