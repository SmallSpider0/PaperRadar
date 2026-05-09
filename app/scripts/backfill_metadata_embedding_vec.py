#!/usr/bin/env python3
from __future__ import annotations

import json

from backend.pg_json_store import execute_sql, fetch_all


def vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.17g}" for value in values) + "]"


def pgvector_column_ready() -> bool:
    row = fetch_all(
        """
        SELECT
          EXISTS (
            SELECT 1
            FROM pg_type
            WHERE typname = 'vector'
          ) AS has_vector_type,
          EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'paper_metadata_embeddings'
              AND column_name = 'embedding_vec'
          ) AS has_embedding_vec
        """
    )[0]
    return bool(row.get("has_vector_type")) and bool(row.get("has_embedding_vec"))


def load_pending_rows(limit: int) -> list[dict]:
    return fetch_all(
        """
        SELECT id, embedding
        FROM paper_metadata_embeddings
        WHERE embedding_vec IS NULL
        ORDER BY created_at ASC
        LIMIT %s
        """,
        (max(1, int(limit)),),
    )


def main() -> None:
    if not pgvector_column_ready():
        raise SystemExit("pgvector or embedding_vec column is not ready")

    batch_size = 200
    total_updated = 0
    while True:
        rows = load_pending_rows(batch_size)
        if not rows:
            break
        for row in rows:
            embedding = row.get("embedding")
            if isinstance(embedding, str):
                embedding = json.loads(embedding)
            if not isinstance(embedding, list) or not embedding:
                continue
            execute_sql(
                """
                UPDATE paper_metadata_embeddings
                SET embedding_vec = %s::vector
                WHERE id = %s
                """,
                (vector_literal(embedding), row["id"]),
            )
            total_updated += 1
        print(f"updated batch: {len(rows)} rows, total_updated={total_updated}")

    print(f"done: updated {total_updated} rows")


if __name__ == "__main__":
    main()
