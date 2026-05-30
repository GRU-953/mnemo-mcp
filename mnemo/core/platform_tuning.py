"""Apple-silicon (and general) hardware detection + recommended local-LLM tuning.

On Apple M-series, Ollama runs on the Metal GPU. The big wins on a unified-memory
machine are:
  - OLLAMA_FLASH_ATTENTION=1   → faster attention on Metal
  - OLLAMA_KV_CACHE_TYPE=q8_0  → ~halves the KV-cache memory (critical at 16 GB,
                                 keeps everything resident → no swap thrash)
  - OLLAMA_MAX_LOADED_MODELS=1 → only one model resident at a time (fits 16 GB and
                                 prevents extract/embed/vision models thrashing)
  - OLLAMA_NUM_PARALLEL=1      → single request stream → lower peak memory

These are read by the Ollama *server* at startup; scripts/install.sh applies them.
"""
from __future__ import annotations

import os
import platform
import subprocess

# Recommended Ollama server environment for local, single-user, 8–16 GB machines.
OLLAMA_TUNING: dict[str, str] = {
    "OLLAMA_FLASH_ATTENTION": "1",
    "OLLAMA_KV_CACHE_TYPE": "q8_0",
    "OLLAMA_MAX_LOADED_MODELS": "1",
    "OLLAMA_NUM_PARALLEL": "1",
}


def _sysctl(key: str) -> str:
    try:
        return subprocess.run(["sysctl", "-n", key], capture_output=True,
                              text=True, timeout=2).stdout.strip()
    except Exception:
        return ""


def hardware_info() -> dict:
    is_arm_mac = platform.system() == "Darwin" and platform.machine() == "arm64"
    info: dict = {
        "os": platform.system(),
        "arch": platform.machine(),
        "apple_silicon": is_arm_mac,
        "cpu_count": os.cpu_count(),
    }
    if is_arm_mac:
        info["chip"] = _sysctl("machdep.cpu.brand_string") or "Apple silicon"
        for key, label in (("hw.perflevel0.physicalcpu", "performance_cores"),
                           ("hw.perflevel1.physicalcpu", "efficiency_cores")):
            v = _sysctl(key)
            if v.isdigit():
                info[label] = int(v)
        mem = _sysctl("hw.memsize")
        if mem.isdigit():
            info["ram_gb"] = round(int(mem) / 1073741824)
        info["gpu"] = "Metal (Apple GPU) via Ollama"
    return info


def recommended_num_ctx(ram_gb: int | None) -> int:
    """Context window sized to available unified memory (with q8 KV cache)."""
    if not ram_gb:
        return 8192
    if ram_gb <= 8:
        return 4096
    if ram_gb <= 16:
        return 8192
    return 16384


def ollama_tuning_status() -> dict:
    """Recommended Ollama tuning vs. what's visible in this process's environment.
    (The values take effect in the Ollama *server*; install.sh sets them there.)"""
    return {
        "recommended": OLLAMA_TUNING,
        "env_seen_here": {k: os.environ.get(k) for k in OLLAMA_TUNING},
        "note": "Set by scripts/install.sh on the Ollama server; restart Ollama to apply.",
    }
