"""Thin client for the local Ollama HTTP API (free, local inference).

All LLM work — extraction, embeddings, image captions — goes through here.
No cloud calls, no API keys, no Claude tokens.
"""
from __future__ import annotations

import json
from typing import Any

import requests

from . import config


def _host() -> str:
    return config.OLLAMA_HOST


def ping(timeout: float = 2.0) -> bool:
    try:
        return requests.get(f"{_host()}/api/version", timeout=timeout).ok
    except Exception:
        return False


def version(timeout: float = 2.0) -> str | None:
    try:
        r = requests.get(f"{_host()}/api/version", timeout=timeout)
        return r.json().get("version") if r.ok else None
    except Exception:
        return None


def list_models(timeout: float = 5.0) -> list[str]:
    try:
        r = requests.get(f"{_host()}/api/tags", timeout=timeout)
        if r.ok:
            return [m.get("name", "") for m in r.json().get("models", [])]
    except Exception:
        pass
    return []


def has_model(name: str) -> bool:
    base = name.split(":")[0]
    for m in list_models():
        if m == name or m.split(":")[0] == base:
            return True
    return False


def generate(
    prompt: str,
    *,
    model: str,
    system: str | None = None,
    fmt: Any | None = None,
    images: list[str] | None = None,
    temperature: float = 0.0,
    num_ctx: int = 8192,
    num_predict: int | None = None,
    keep_alive: str | None = None,
    timeout: float = 600.0,
) -> str:
    """Single-shot completion. `fmt` may be "json" or a JSON-schema dict
    (Ollama structured outputs). `keep_alive` keeps the model resident between
    calls (e.g. "30m") to avoid reloads during a build. Returns response text."""
    options: dict[str, Any] = {"temperature": temperature, "num_ctx": num_ctx}
    if num_predict is not None:
        options["num_predict"] = num_predict
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": options,
    }
    if system:
        payload["system"] = system
    if fmt is not None:
        payload["format"] = fmt
    if images:
        payload["images"] = images
    if keep_alive is not None:
        payload["keep_alive"] = keep_alive
    r = requests.post(f"{_host()}/api/generate", json=payload, timeout=timeout)
    r.raise_for_status()
    return (r.json().get("response") or "").strip()


def embed(texts: list[str], *, model: str | None = None, timeout: float = 180.0) -> list[list[float]]:
    """Batch embeddings. Prefers the newer /api/embed, falls back to /api/embeddings."""
    model = model or config.EMBED_MODEL
    if not texts:
        return []
    try:
        r = requests.post(f"{_host()}/api/embed", json={"model": model, "input": texts}, timeout=timeout)
        if r.ok:
            embs = r.json().get("embeddings")
            if embs and len(embs) == len(texts):
                return embs
    except Exception:
        pass
    out: list[list[float]] = []
    for t in texts:
        rr = requests.post(f"{_host()}/api/embeddings", json={"model": model, "prompt": t}, timeout=timeout)
        rr.raise_for_status()
        out.append(rr.json().get("embedding", []))
    return out


def parse_json(text: str) -> Any:
    """Best-effort JSON parse of an LLM response (handles code fences and
    leading/trailing prose)."""
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        nl = t.find("\n")
        if nl != -1:
            t = t[nl + 1:]
        t = t.strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    # Salvage the outermost {...} or [...]
    for open_c, close_c in (("{", "}"), ("[", "]")):
        i, j = t.find(open_c), t.rfind(close_c)
        if i != -1 and j != -1 and j > i:
            try:
                return json.loads(t[i:j + 1])
            except Exception:
                continue
    return None
