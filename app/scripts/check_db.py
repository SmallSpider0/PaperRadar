#!/usr/bin/env python3
from __future__ import annotations

import subprocess

from backend.db import db_settings


def main() -> int:
    command = [
        "psql",
        db_settings.dsn,
        "-Atqc",
        "SELECT current_database(), current_user;",
    ]
    return subprocess.call(command)


if __name__ == "__main__":
    raise SystemExit(main())
