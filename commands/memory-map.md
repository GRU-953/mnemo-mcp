---
description: Open the interactive HTML mind map (knowledge graph) for a project
argument-hint: "[optional: project name]"
---

# Open the mind map

Open the self-contained interactive knowledge graph in the browser — nodes
color-coded by type, searchable, click any node for its description, facts, and
source documents.

## Instructions

1. Call `memory_open_mindmap` (pass `project` if the user named one; otherwise it
   uses the only/most-relevant project).
2. If no mind map exists yet, offer to build memory first with `memory_build`.
3. Report the file path so the user can re-open it anytime.
