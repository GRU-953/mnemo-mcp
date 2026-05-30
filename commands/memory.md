---
description: Recall project memory — load the overview or answer a question from the local graph
argument-hint: "[a question, or blank for the project overview]"
---

# Recall project memory

Use the local memory graph to restore context or answer a question **without
reading documents into the conversation** (that is the whole point — it keeps token
use tiny).

## Instructions

1. If `$ARGUMENTS` is empty, call `memory_overview` and present the compact digest.
2. Otherwise call `memory_query` with the question. It returns only the most
   relevant entities + facts (a small subgraph with provenance), not whole files.
   - To search across every project, pass `scope="all"`.
3. If the user wants to dig into one entity, call `memory_expand` on it.
4. Cite provenance (the source files shown) when relevant.
5. Only if memory genuinely lacks the answer, say so and offer to `memory_build` /
   `memory_update`, or to read a specific source file directly.

Never dump entire documents into context when a `memory_query` will do.
