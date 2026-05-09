#!/usr/bin/env python3
from pathlib import Path

from backend.db import db_settings


def main() -> None:
    schema_path = Path(__file__).resolve().parents[1] / "backend" / "schema.sql"
    print("PaperRadar Stage 1 DB init plan")
    print(f"DSN: {db_settings.dsn}")
    print(f"Schema file: {schema_path}")
    print("Next step: install PostgreSQL driver and execute schema.sql against the target database.")


if __name__ == "__main__":
    main()
