#!/usr/bin/env python3
import subprocess
from pathlib import Path

from backend.db import db_settings


def main() -> int:
    schema_path = Path(__file__).resolve().parents[1] / "backend" / "schema.sql"
    command = [
        "psql",
        db_settings.dsn,
        "-f",
        str(schema_path),
    ]
    print("Running:", " ".join(command))
    return subprocess.call(command)


if __name__ == "__main__":
    raise SystemExit(main())
