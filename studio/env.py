"""Load key=value settings from a project-root .env into the process environment.

Kept separate from app.py so it is unit-testable and reusable. The Streamlit
process is launched via `sh -c` (see .claude/launch.json and the deploy runner),
which does NOT source ~/.zshrc — so shell exports never reach it. Reading a
gitignored .env here bridges that gap without leaking secrets.

Existing real environment variables always win, so a shell export or a hosting
provider's secrets panel takes precedence over the file.
"""
from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(root: Path | str) -> dict[str, str]:
    """Load ``<root>/.env`` into ``os.environ`` without overriding existing vars.

    Lines are ``KEY=VALUE``; blank lines and ``#`` comments are skipped, and a
    single layer of surrounding single/double quotes is stripped from the value.
    Returns the mapping of keys it actually set (helpful for tests and logging).
    A missing file is a no-op that returns ``{}``.
    """
    env_file = Path(root) / ".env"
    if not env_file.exists():
        return {}
    applied: dict[str, str] = {}
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val
            applied[key] = val
    return applied
