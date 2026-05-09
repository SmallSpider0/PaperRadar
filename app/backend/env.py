from __future__ import annotations

import os
from pathlib import Path


_loaded = False


def load_local_env() -> None:
    global _loaded
    if _loaded:
        return
    env_path = Path(__file__).resolve().parents[2] / ".env.local"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())
    _loaded = True
