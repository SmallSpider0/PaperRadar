#!/usr/bin/env python3
"""Import the public PaperRadar paper seed into an existing schema.

The bundled seed is stored as a plain PostgreSQL dump so it is easy to inspect
in git.  For the all-in-one Docker image we import only data rows, in
foreign-key-safe order, into the schema created by ``backend/schema.sql``.
"""

from __future__ import annotations

import gzip
import os
import re
import tempfile
from pathlib import Path

import psycopg

from backend.db import db_settings


COPY_RE = re.compile(r"^COPY public\.([A-Za-z0-9_]+) \((.+)\) FROM stdin;$")

TABLE_ORDER = [
    "venues",
    "venue_editions",
    "papers",
    "paper_external_ids",
    "paper_files",
    "paper_metadata_embeddings",
    "paper_parse_jobs",
    "paper_topic_profiles",
    "paper_topic_profile_runs",
    "query_embedding_cache",
    "query_translation_cache",
    "query_translation_rules",
]

TRUNCATE_TABLES = list(reversed(TABLE_ORDER))


def _parse_columns(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",")]


def _collect_copy_blocks(seed_path: Path, workdir: Path) -> tuple[dict[str, Path], dict[str, list[str]]]:
    block_paths: dict[str, Path] = {}
    block_columns: dict[str, list[str]] = {}
    active_table: str | None = None
    active_file = None

    with gzip.open(seed_path, "rt", encoding="utf-8", newline="") as fh:
        for raw_line in fh:
            line = raw_line.rstrip("\n")
            if active_table:
                if line == r"\.":
                    active_file.close()
                    active_file = None
                    active_table = None
                else:
                    active_file.write(raw_line)
                continue

            match = COPY_RE.match(line)
            if not match:
                continue
            table, raw_columns = match.groups()
            if table not in TABLE_ORDER:
                active_table = table
                active_file = open(os.devnull, "w", encoding="utf-8")
                continue

            block_columns[table] = _parse_columns(raw_columns)
            block_path = workdir / f"{table}.copy"
            block_paths[table] = block_path
            active_table = table
            active_file = block_path.open("w", encoding="utf-8", newline="")

    return block_paths, block_columns


def _table_columns(cur: psycopg.Cursor, table: str) -> set[str]:
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        """,
        (table,),
    )
    return {row[0] for row in cur.fetchall()}


def _copy_table(
    cur: psycopg.Cursor,
    table: str,
    source_path: Path,
    source_columns: list[str],
    target_columns: set[str],
) -> int:
    selected = [(idx, col) for idx, col in enumerate(source_columns) if col in target_columns]
    if not selected:
        return 0

    selected_indexes = [idx for idx, _ in selected]
    selected_columns = [col for _, col in selected]
    copied = 0

    with source_path.open("r", encoding="utf-8", newline="") as fh:
        with cur.copy(f"COPY {table} ({', '.join(selected_columns)}) FROM STDIN") as copy:
            for raw_line in fh:
                fields = raw_line.rstrip("\n").split("\t")
                copy.write("\t".join(fields[idx] for idx in selected_indexes) + "\n")
                copied += 1

    return copied


def main() -> int:
    seed_path = Path(os.environ.get("PAPERRADAR_SEED_PATH", "data/seed/paperradar-paperdata.sql.gz"))
    if not seed_path.is_file():
        raise SystemExit(f"seed file not found: {seed_path}")

    with tempfile.TemporaryDirectory(prefix="paperradar-seed-") as tmp:
        block_paths, block_columns = _collect_copy_blocks(seed_path, Path(tmp))

        with psycopg.connect(db_settings.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM papers")
                paper_count = cur.fetchone()[0]
                if paper_count:
                    print(f"skip seed import: papers table already has {paper_count} rows")
                    return 0

                present_tables = [table for table in TRUNCATE_TABLES if table in block_paths]
                cur.execute(
                    "TRUNCATE TABLE "
                    + ", ".join(present_tables)
                    + " RESTART IDENTITY CASCADE"
                )

                total: dict[str, int] = {}
                for table in TABLE_ORDER:
                    source_path = block_paths.get(table)
                    if not source_path:
                        continue
                    columns = _table_columns(cur, table)
                    total[table] = _copy_table(
                        cur,
                        table,
                        source_path,
                        block_columns[table],
                        columns,
                    )

                cur.execute(
                    """
                    SELECT setval(
                        'query_translation_rules_id_seq',
                        COALESCE((SELECT MAX(id) FROM query_translation_rules), 1),
                        true
                    )
                    WHERE to_regclass('query_translation_rules_id_seq') IS NOT NULL
                    """
                )

            conn.commit()

    print("seed import complete: " + ", ".join(f"{k}={v}" for k, v in total.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
