"""Self-update: keep the plugin on the latest GitHub release.

The plugin is installed as a git checkout, so updating is a fast-forward `git pull`
to the newest released tag. Exposed via the CLI (`mnemo self-update` /
`mnemo check-update`), an MCP tool (`memory_self_update`), and an optional
non-blocking check on server start (MNEMO_AUTO_UPDATE).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path

DEFAULT_REPO = "GRU-953/mnemo-mcp"


def repo_slug() -> str:
    return os.environ.get("MNEMO_REPO", DEFAULT_REPO)


def _plugin_root() -> Path:
    # mnemo/core/updater.py -> mnemo/core -> mnemo -> <repo root>
    return Path(__file__).resolve().parents[2]


def is_git_checkout() -> bool:
    return (_plugin_root() / ".git").exists()


def current_version() -> str:
    try:
        from mnemo import __version__
        return __version__
    except Exception:
        return "0.0.0"


def _ver_key(tag: str) -> tuple:
    nums = [int(x) for x in re.findall(r"\d+", tag or "")][:3]
    return tuple(nums + [0] * (3 - len(nums)))


def _git(*args: str, timeout: float = 30.0) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(_plugin_root()), *args],
                          capture_output=True, text=True, timeout=timeout)


def latest_release(timeout: float = 8.0) -> dict | None:
    """Latest released tag from GitHub (Releases API, falling back to remote tags)."""
    url = f"https://api.github.com/repos/{repo_slug()}/releases/latest"
    try:
        req = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json", "User-Agent": "mnemo-updater"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
        if data.get("tag_name"):
            return {"tag": data["tag_name"], "name": data.get("name"), "url": data.get("html_url")}
    except Exception:
        pass
    try:
        res = _git("ls-remote", "--tags", "--refs", "origin", timeout=timeout)
        tags = [ln.split("refs/tags/")[-1] for ln in res.stdout.splitlines() if "refs/tags/" in ln]
        tags = [t for t in tags if re.match(r"v?\d", t)]
        if tags:
            tags.sort(key=_ver_key)
            return {"tag": tags[-1], "name": tags[-1], "url": None}
    except Exception:
        pass
    return None


def check_update() -> dict:
    cur = current_version()
    rel = latest_release()
    if not rel or not rel.get("tag"):
        return {"available": False, "current": cur, "latest": None, "reason": "no release info / offline"}
    latest = rel["tag"].lstrip("v")
    return {"available": _ver_key(latest) > _ver_key(cur), "current": cur,
            "latest": latest, "tag": rel["tag"], "url": rel.get("url")}


def self_update(*, reinstall: bool = True) -> dict:
    """Fast-forward the plugin checkout to the latest released code (safe: never
    discards local changes — an ff-only pull simply fails if the tree diverged)."""
    if not is_git_checkout():
        return {"updated": False, "reason": "plugin is not a git checkout; reinstall via the marketplace"}
    before = _git("rev-parse", "HEAD").stdout.strip()
    _git("fetch", "--tags", "origin", timeout=60)
    pull = _git("pull", "--ff-only", "origin", "main", timeout=60)
    after = _git("rev-parse", "HEAD").stdout.strip()
    updated = bool(before) and before != after
    out = (pull.stdout or pull.stderr or "").strip()
    result = {"updated": updated, "before": before[:8], "after": after[:8],
              "version": current_version(), "detail": out[-300:]}
    if updated and reinstall:
        venv_py = _plugin_root() / ".venv" / "bin" / "python"
        if venv_py.exists():
            try:
                subprocess.run([str(venv_py), "-m", "pip", "install", "-q", "-e", ".", "--no-deps"],
                               cwd=str(_plugin_root()), timeout=180, capture_output=True)
            except Exception:
                pass
        result["note"] = "Updated — restart Claude/Ollama session to load the new code."
    return result


def auto_update_on_start() -> None:
    """Non-blocking best-effort check/update at server start. Controlled by
    MNEMO_AUTO_UPDATE: 'auto' (ff-pull latest), 'check' (log only), 'off'."""
    mode = os.environ.get("MNEMO_AUTO_UPDATE", "check").lower()
    if mode == "off":
        return

    def _run():
        try:
            info = check_update()
            if not info.get("available"):
                return
            if mode == "auto":
                self_update()
            else:  # "check": notify only — never pulls/executes code unattended
                import sys
                print(f"[mnemo] update available: {info.get('current')} -> {info.get('latest')} — "
                      f"run memory_self_update (or `mnemo self-update`).", file=sys.stderr, flush=True)
        except Exception:
            pass

    import threading
    threading.Thread(target=_run, daemon=True).start()
