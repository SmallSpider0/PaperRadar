#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from backend.pg_json_store import execute_sql, fetch_all, run_sql

BASE_DIR = Path(__file__).resolve().parents[2]
GENERATED_DIR = BASE_DIR / 'data' / 'generated'

VENUE_MAP = {
    'USENIX_SECURITY': {
        'venue_id': 'venue_usenix_security',
        'code': 'USENIX_SECURITY',
        'name': 'USENIX Security Symposium',
        'publisher_type': 'usenix',
        'homepage': 'https://www.usenix.org/conference/usenixsecurity25',
    },
    'NDSS': {
        'venue_id': 'venue_ndss',
        'code': 'NDSS',
        'name': 'NDSS Symposium',
        'publisher_type': 'internet-society',
        'homepage': 'https://www.ndss-symposium.org/ndss2025/',
    },
    'IEEE_SP': {
        'venue_id': 'venue_ieee_sp',
        'code': 'IEEE_SP',
        'name': 'IEEE Symposium on Security and Privacy',
        'publisher_type': 'ieee',
        'homepage': 'https://www.ieee-security.org/TC/SP2025/',
    },
    'ACM_CCS': {
        'venue_id': 'venue_acm_ccs',
        'code': 'ACM_CCS',
        'name': 'ACM Conference on Computer and Communications Security',
        'publisher_type': 'acm',
        'homepage': 'https://www.sigsac.org/ccs/CCS2025/',
    },
}


def q(text: str | None) -> str:
    if text is None:
        return 'NULL'
    return "'" + str(text).replace("'", "''") + "'"


def qjson(obj) -> str:
    return "'" + json.dumps(obj, ensure_ascii=False).replace("'", "''") + "'::jsonb"


def vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.17g}" for value in values) + "]"


def safe_paper_id(paper_url: str) -> str:
    return 'paper_' + hashlib.sha256(paper_url.encode('utf-8')).hexdigest()[:16]


def pgvector_column_ready() -> bool:
    raw = os.getenv("PAPERRADAR_ENABLE_PGVECTOR", "1").strip().lower()
    if raw in {"0", "false", "off", "no"}:
        return False
    try:
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
    except Exception:
        return False
    return bool(row.get("has_vector_type")) and bool(row.get("has_embedding_vec"))


def upsert_reference_data(records: list[dict]) -> None:
    venue_keys = sorted({record['venue_code'] for record in records if record.get('venue_code') in VENUE_MAP})
    for venue_code in venue_keys:
        cfg = VENUE_MAP[venue_code]
        sql = f'''
        INSERT INTO venues (id, code, name, publisher_type, homepage)
        VALUES ({q(cfg['venue_id'])}, {q(cfg['code'])}, {q(cfg['name'])}, {q(cfg['publisher_type'])}, {q(cfg['homepage'])})
        ON CONFLICT (id) DO UPDATE SET
          code = EXCLUDED.code,
          name = EXCLUDED.name,
          publisher_type = EXCLUDED.publisher_type,
          homepage = EXCLUDED.homepage,
          updated_at = NOW();
        '''
        run_sql(sql)

    edition_keys = sorted({(record['venue_code'], int(record['year'])) for record in records if record.get('venue_code') in VENUE_MAP})
    for venue_code, year in edition_keys:
        cfg = VENUE_MAP[venue_code]
        edition_id = f"edition_{venue_code.lower()}_{year}"
        sql = f'''
        INSERT INTO venue_editions (id, venue_id, year, label, program_url, metadata_source)
        VALUES ({q(edition_id)}, {q(cfg['venue_id'])}, {year}, {q(f'{cfg['name']} {year}')}, {q(cfg['homepage'])}, 'crawler')
        ON CONFLICT (id) DO UPDATE SET
          venue_id = EXCLUDED.venue_id,
          year = EXCLUDED.year,
          label = EXCLUDED.label,
          program_url = EXCLUDED.program_url,
          metadata_source = EXCLUDED.metadata_source,
          updated_at = NOW();
        '''
        run_sql(sql)


def ingest_records(records: list[dict]) -> list[str]:
    ingested_paper_ids: list[str] = []
    vector_ready = pgvector_column_ready()
    for record in records:
        venue_code = record.get('venue_code')
        if venue_code not in VENUE_MAP:
            continue
        year = int(record.get('year') or 0)
        edition_id = f"edition_{venue_code.lower()}_{year}"
        paper_id = safe_paper_id(record.get('paper_url', ''))
        sql = f'''
        INSERT INTO papers (
          id, venue_edition_id, title, abstract, authors_text, paper_url,
          source_pdf_url, source, content_policy, fulltext_status, report_status, raw_meta_json
        ) VALUES (
          {q(paper_id)}, {q(edition_id)}, {q(record.get('title'))}, {q(record.get('abstract'))},
          {q(record.get('authors_text'))}, {q(record.get('paper_url'))}, {q(record.get('source_pdf_url'))},
          {q(record.get('source'))}, {q(record.get('content_policy') or 'on_demand_allowed')},
          'not_requested', 'not_requested', {qjson(record)}
        )
        ON CONFLICT (id) DO UPDATE SET
          venue_edition_id = EXCLUDED.venue_edition_id,
          title = EXCLUDED.title,
          abstract = EXCLUDED.abstract,
          authors_text = EXCLUDED.authors_text,
          paper_url = EXCLUDED.paper_url,
          source_pdf_url = EXCLUDED.source_pdf_url,
          source = EXCLUDED.source,
          content_policy = EXCLUDED.content_policy,
          raw_meta_json = EXCLUDED.raw_meta_json,
          updated_at = NOW();
        '''
        run_sql(sql)
        ingested_paper_ids.append(paper_id)

        embedding = record.get('embedding')
        if isinstance(embedding, list) and embedding:
            content_hash = hashlib.sha256(
                f"{record.get('title','')}\n\n{record.get('abstract') or ''}".encode('utf-8')
            ).hexdigest()
            emb_id = f"emb_{paper_id}"
            if vector_ready:
                execute_sql(
                    """
                    INSERT INTO paper_metadata_embeddings (
                      id, paper_id, model_name, embedding, embedding_vec, content_hash
                    ) VALUES (
                      %s, %s, 'gemini-embedding-001', %s::jsonb, %s::vector, %s
                    )
                    ON CONFLICT (id) DO UPDATE SET
                      paper_id = EXCLUDED.paper_id,
                      model_name = EXCLUDED.model_name,
                      embedding = EXCLUDED.embedding,
                      embedding_vec = EXCLUDED.embedding_vec,
                      content_hash = EXCLUDED.content_hash;
                    """,
                    (
                        emb_id,
                        paper_id,
                        json.dumps(embedding, ensure_ascii=False),
                        vector_literal(embedding),
                        content_hash,
                    ),
                )
            else:
                emb_sql = f'''
                INSERT INTO paper_metadata_embeddings (id, paper_id, model_name, embedding, content_hash)
                VALUES ({q(emb_id)}, {q(paper_id)}, 'gemini-embedding-001', {qjson(embedding)}, {q(content_hash)})
                ON CONFLICT (id) DO UPDATE SET
                  paper_id = EXCLUDED.paper_id,
                  model_name = EXCLUDED.model_name,
                  embedding = EXCLUDED.embedding,
                  content_hash = EXCLUDED.content_hash;
                '''
                run_sql(emb_sql)
    return ingested_paper_ids


def main() -> None:
    records: list[dict] = []
    for path in GENERATED_DIR.glob('*_normalized.json'):
        records.extend(json.loads(path.read_text(encoding='utf-8')))
    upsert_reference_data(records)
    ingested_paper_ids = ingest_records(records)
    print(f'ingested papers: {len(records)}')

    if os.getenv('PAPERRADAR_TOPIC_INCREMENTAL', '1') != '0' and ingested_paper_ids:
        script_path = BASE_DIR / 'app' / 'scripts' / 'build_topic_profiles_incremental.py'
        env = os.environ.copy()
        subprocess.run(
            [sys.executable, str(script_path), *ingested_paper_ids],
            check=True,
            env=env,
        )


if __name__ == '__main__':
    main()
