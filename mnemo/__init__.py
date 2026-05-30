"""Mnemo — local, token-free, graph-based project memory for Claude.

Everything heavy (document conversion, knowledge extraction, embeddings,
visualization) runs locally via MarkItDown + Tesseract + Ollama. Claude only
ever sees compact metadata or a small, relevant subgraph — never raw documents.
"""

__version__ = "0.5.0"
