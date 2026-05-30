"""On-demand Ollama lifecycle management (Apple-silicon memory friendly).

The local LLM should run *only while work is happening*. So:
  - `ensure_up()` is called before any LLM use — if Ollama isn't running, Mnemo
    starts it (with the Metal/memory tuning) and records that *it* started it.
  - every LLM call refreshes an activity timestamp.
  - a detached watchdog stops the server (and unloads models) after
    MNEMO_OLLAMA_IDLE seconds of inactivity — but only a server Mnemo started
    (it never kills a brew/user-launched Ollama).

Set MNEMO_OLLAMA_LIFECYCLE=off to disable management entirely.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import platform_tuning

_START_LOCK = threading.Lock()


def _host() -> str:
    return os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")


def _state_dir() -> Path:
    root = os.environ.get("MNEMO_HOME") or os.path.join(os.path.expanduser("~"), ".claude-memory")
    d = Path(root).expanduser() / ".ollama"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _last_use() -> Path:
    return _state_dir() / "last_use"


def _started_marker() -> Path:
    return _state_dir() / "started_by_mnemo"


def _watchdog_lock() -> Path:
    return _state_dir() / "watchdog.pid"


def idle_timeout() -> int:
    v = os.environ.get("MNEMO_OLLAMA_IDLE", "300")
    return int(v) if v.isdigit() else 300


def keep_alive() -> str:
    """Model-level unload window (aligns with the idle timeout)."""
    return os.environ.get("MNEMO_KEEP_ALIVE") or f"{max(1, idle_timeout() // 60)}m"


def managed() -> bool:
    return os.environ.get("MNEMO_OLLAMA_LIFECYCLE", "managed").lower() != "off"


def touch_activity() -> None:
    try:
        _last_use().write_text(str(time.time()))
    except Exception:
        pass


def is_up(timeout: float = 2.0) -> bool:
    import requests
    try:
        return requests.get(f"{_host()}/api/version", timeout=timeout).ok
    except Exception:
        return False


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def ensure_up(timeout: float = 30.0) -> bool:
    """Guarantee Ollama is reachable, starting it on demand if needed. Cheap when
    already up (a ping + activity touch)."""
    touch_activity()
    if is_up():
        return True
    if not managed():
        return is_up()
    with _START_LOCK:
        if is_up():
            return True
        env = {**os.environ, **platform_tuning.OLLAMA_TUNING}
        try:
            proc = subprocess.Popen(
                ["ollama", "serve"], env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            _started_marker().write_text(str(proc.pid))
        except Exception:
            return is_up()
        deadline = time.time() + timeout
        while time.time() < deadline:
            if is_up():
                break
            time.sleep(0.5)
        touch_activity()
        _ensure_watchdog()
        return is_up()


def _ensure_watchdog() -> None:
    lock = _watchdog_lock()
    if lock.exists():
        try:
            if _alive(int(lock.read_text().strip())):
                return
        except Exception:
            pass
    try:
        p = subprocess.Popen(
            [sys.executable, "-m", "mnemo.core.lifecycle", "--watchdog"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        lock.write_text(str(p.pid))
    except Exception:
        pass


def stop_ollama() -> dict:
    """Unload models and stop the server — only if Mnemo started it."""
    marker = _started_marker()
    if not marker.exists():
        return {"stopped": False, "reason": "not started by Mnemo"}
    import requests
    try:  # unload any loaded models first (frees memory promptly)
        r = requests.get(f"{_host()}/api/ps", timeout=3)
        for m in (r.json().get("models") or []):
            if m.get("name"):
                subprocess.run(["ollama", "stop", m["name"]], capture_output=True, timeout=10)
    except Exception:
        pass
    stopped = False
    try:
        pid = int(marker.read_text().strip())
        if _alive(pid):
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except Exception:
                os.kill(pid, signal.SIGTERM)
            stopped = True
    except Exception:
        pass
    try:
        marker.unlink()
    except Exception:
        pass
    return {"stopped": stopped}


def status() -> dict:
    return {
        "managed": managed(),
        "up": is_up(),
        "started_by_mnemo": _started_marker().exists(),
        "idle_timeout_secs": idle_timeout(),
        "keep_alive": keep_alive(),
        "watchdog_running": _watchdog_lock().exists() and _alive_safe(_watchdog_lock()),
    }


def _alive_safe(lock: Path) -> bool:
    try:
        return _alive(int(lock.read_text().strip()))
    except Exception:
        return False


def _watchdog_loop() -> None:
    to = idle_timeout()
    poll = min(30, max(5, to // 4))
    while True:
        time.sleep(poll)
        try:
            lu = float(_last_use().read_text().strip()) if _last_use().exists() else 0.0
        except Exception:
            lu = time.time()
        if time.time() - lu > to:
            if _started_marker().exists():
                stop_ollama()
            try:
                _watchdog_lock().unlink()
            except Exception:
                pass
            return
        if not is_up() and not _started_marker().exists():
            try:
                _watchdog_lock().unlink()
            except Exception:
                pass
            return


if __name__ == "__main__":
    if "--watchdog" in sys.argv:
        _watchdog_loop()
