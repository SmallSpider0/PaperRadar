CREATE TABLE IF NOT EXISTS venues (
    id TEXT PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    publisher_type TEXT NOT NULL,
    homepage TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS venue_editions (
    id TEXT PRIMARY KEY,
    venue_id TEXT NOT NULL REFERENCES venues(id),
    year INTEGER NOT NULL,
    label TEXT NOT NULL,
    program_url TEXT,
    metadata_source TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (venue_id, year)
);

CREATE TABLE IF NOT EXISTS papers (
    id TEXT PRIMARY KEY,
    venue_edition_id TEXT NOT NULL REFERENCES venue_editions(id),
    title TEXT NOT NULL,
    abstract TEXT,
    authors_text TEXT,
    doi TEXT,
    paper_url TEXT,
    source_pdf_url TEXT,
    source TEXT NOT NULL,
    content_policy TEXT NOT NULL,
    fulltext_status TEXT NOT NULL DEFAULT 'not_requested',
    report_status TEXT NOT NULL DEFAULT 'not_requested',
    published_at TIMESTAMPTZ,
    raw_meta_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS paper_external_ids (
    id TEXT PRIMARY KEY,
    paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    source_name TEXT NOT NULL,
    external_id TEXT NOT NULL,
    external_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source_name, external_id)
);

CREATE TABLE IF NOT EXISTS paper_files (
    id TEXT PRIMARY KEY,
    paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    file_type TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    source_url TEXT,
    sha256 TEXT,
    size_bytes BIGINT,
    mime_type TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS paper_parse_jobs (
    id TEXT PRIMARY KEY,
    paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    job_type TEXT NOT NULL,
    trigger_source TEXT NOT NULL,
    status TEXT NOT NULL,
    error_message TEXT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS paper_metadata_embeddings (
    id TEXT PRIMARY KEY,
    paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    model_name TEXT NOT NULL,
    embedding JSONB NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_paper_metadata_embeddings_paper_id
ON paper_metadata_embeddings(paper_id);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_available_extensions
        WHERE name = 'vector'
    ) THEN
        EXECUTE 'CREATE EXTENSION IF NOT EXISTS vector';
        EXECUTE 'ALTER TABLE paper_metadata_embeddings ADD COLUMN IF NOT EXISTS embedding_vec vector(3072)';
        IF EXISTS (
            SELECT 1
            FROM pg_type
            WHERE typname = 'halfvec'
        ) THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_paper_metadata_embeddings_embedding_halfvec_hnsw ON paper_metadata_embeddings USING hnsw ((embedding_vec::halfvec(3072)) halfvec_cosine_ops)';
        ELSIF 3072 <= 2000 THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_paper_metadata_embeddings_embedding_vec_hnsw ON paper_metadata_embeddings USING hnsw (embedding_vec vector_cosine_ops)';
        ELSE
            RAISE NOTICE 'skip HNSW index for embedding_vec: current pgvector package cannot index 3072-dim vector and halfvec is unavailable';
        END IF;
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS paper_topic_profiles (
    id TEXT PRIMARY KEY,
    paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    model_name TEXT NOT NULL,
    topic_tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    topic_summary TEXT,
    content_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (paper_id, model_name)
);

CREATE INDEX IF NOT EXISTS idx_paper_topic_profiles_paper_id
ON paper_topic_profiles(paper_id);

CREATE INDEX IF NOT EXISTS idx_papers_search_fts
ON papers
USING GIN (
    to_tsvector(
        'simple',
        coalesce(title, '') || ' ' || coalesce(abstract, '') || ' ' || coalesce(authors_text, '')
    )
);

CREATE INDEX IF NOT EXISTS idx_paper_topic_profiles_search_fts
ON paper_topic_profiles
USING GIN (
    to_tsvector(
        'simple',
        coalesce(topic_summary, '') || ' ' || coalesce(topic_tags::text, '')
    )
);

CREATE TABLE IF NOT EXISTS paper_topic_profile_runs (
    id TEXT PRIMARY KEY,
    paper_id TEXT REFERENCES papers(id) ON DELETE SET NULL,
    model_name TEXT NOT NULL,
    status TEXT NOT NULL,
    finish_reason TEXT,
    token_usage_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message TEXT,
    raw_response_text TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_paper_topic_profile_runs_paper_id
ON paper_topic_profile_runs(paper_id, created_at DESC);

CREATE TABLE IF NOT EXISTS subscriptions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    query_text TEXT,
    filters_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    threshold DOUBLE PRECISION,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS subscription_matches (
    id TEXT PRIMARY KEY,
    subscription_id TEXT NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
    paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    match_score DOUBLE PRECISION,
    match_reason TEXT,
    evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS notifications (
    id TEXT PRIMARY KEY,
    subscription_id TEXT NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
    paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rag_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT,
    latest_query TEXT,
    latest_intent TEXT,
    latest_answer TEXT,
    message_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rag_messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES rag_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    structured_query_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    answer_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS review_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT,
    query TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'prepared',
    confirmed BOOLEAN NOT NULL DEFAULT FALSE,
    prepared_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    review_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_review_sessions_user_updated
ON review_sessions(user_id, updated_at DESC, created_at DESC);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_username
ON users(username);

CREATE TABLE IF NOT EXISTS user_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_token_hash TEXT NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    ip TEXT,
    user_agent TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_sessions_token_hash
ON user_sessions(session_token_hash);

CREATE INDEX IF NOT EXISTS idx_user_sessions_expires_at
ON user_sessions(expires_at);

CREATE TABLE IF NOT EXISTS api_usage_logs (
    id BIGSERIAL PRIMARY KEY,
    path TEXT NOT NULL,
    method TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    latency_ms INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_usage_logs_created_at
ON api_usage_logs(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_api_usage_logs_path_created_at
ON api_usage_logs(path, created_at DESC);

CREATE TABLE IF NOT EXISTS llm_usage_logs (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    model TEXT NOT NULL,
    finish_reason TEXT,
    prompt_tokens BIGINT NOT NULL DEFAULT 0,
    completion_tokens BIGINT NOT NULL DEFAULT 0,
    total_tokens BIGINT NOT NULL DEFAULT 0,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_llm_usage_logs_created_at
ON llm_usage_logs(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_llm_usage_logs_source_created_at
ON llm_usage_logs(source, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_llm_usage_logs_model_created_at
ON llm_usage_logs(model, created_at DESC);

CREATE TABLE IF NOT EXISTS query_translation_cache (
    query_hash TEXT PRIMARY KEY,
    query_text TEXT NOT NULL,
    normalized_query TEXT NOT NULL,
    normalized_key TEXT,
    cache_scope TEXT NOT NULL DEFAULT 'raw',
    canonical_query_hash TEXT,
    english_aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
    chinese_aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
    canonical_topics JSONB NOT NULL DEFAULT '[]'::jsonb,
    prototype_hints JSONB NOT NULL DEFAULT '[]'::jsonb,
    query_language TEXT NOT NULL DEFAULT 'unknown',
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    first_hit_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_hit_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    hit_count INTEGER NOT NULL DEFAULT 1,
    expires_at TIMESTAMPTZ,
    is_pinned BOOLEAN NOT NULL DEFAULT FALSE,
    query_kind TEXT NOT NULL DEFAULT 'normal',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE query_translation_cache ADD COLUMN IF NOT EXISTS first_hit_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE query_translation_cache ADD COLUMN IF NOT EXISTS last_hit_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE query_translation_cache ADD COLUMN IF NOT EXISTS hit_count INTEGER NOT NULL DEFAULT 1;
ALTER TABLE query_translation_cache ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;
ALTER TABLE query_translation_cache ADD COLUMN IF NOT EXISTS is_pinned BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE query_translation_cache ADD COLUMN IF NOT EXISTS query_kind TEXT NOT NULL DEFAULT 'normal';
ALTER TABLE query_translation_cache ADD COLUMN IF NOT EXISTS normalized_key TEXT;
ALTER TABLE query_translation_cache ADD COLUMN IF NOT EXISTS cache_scope TEXT NOT NULL DEFAULT 'raw';
ALTER TABLE query_translation_cache ADD COLUMN IF NOT EXISTS canonical_query_hash TEXT;

CREATE INDEX IF NOT EXISTS idx_query_translation_cache_expires_at
ON query_translation_cache(expires_at)
WHERE is_pinned = FALSE;

CREATE INDEX IF NOT EXISTS idx_query_translation_cache_normalized_key
ON query_translation_cache(normalized_key, model, prompt_version);

CREATE INDEX IF NOT EXISTS idx_query_translation_cache_canonical_query_hash
ON query_translation_cache(canonical_query_hash);

CREATE TABLE IF NOT EXISTS query_translation_rules (
    id BIGSERIAL PRIMARY KEY,
    pattern TEXT NOT NULL UNIQUE,
    match_mode TEXT NOT NULL DEFAULT 'contains',
    normalized_query TEXT NOT NULL,
    english_aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
    canonical_topics JSONB NOT NULL DEFAULT '[]'::jsonb,
    prototype_hints JSONB NOT NULL DEFAULT '[]'::jsonb,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.55,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    priority INTEGER NOT NULL DEFAULT 100,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS query_embedding_cache (
    query_hash TEXT PRIMARY KEY,
    query_text TEXT NOT NULL,
    normalized_key TEXT,
    cache_scope TEXT NOT NULL DEFAULT 'raw',
    canonical_query_hash TEXT,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    task_type TEXT NOT NULL DEFAULT 'RETRIEVAL_QUERY',
    embedding JSONB NOT NULL,
    embedding_dim INTEGER NOT NULL,
    first_hit_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_hit_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    hit_count INTEGER NOT NULL DEFAULT 1,
    expires_at TIMESTAMPTZ,
    is_pinned BOOLEAN NOT NULL DEFAULT FALSE,
    query_kind TEXT NOT NULL DEFAULT 'normal',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE query_embedding_cache ADD COLUMN IF NOT EXISTS normalized_key TEXT;
ALTER TABLE query_embedding_cache ADD COLUMN IF NOT EXISTS cache_scope TEXT NOT NULL DEFAULT 'raw';
ALTER TABLE query_embedding_cache ADD COLUMN IF NOT EXISTS canonical_query_hash TEXT;
ALTER TABLE query_embedding_cache ADD COLUMN IF NOT EXISTS first_hit_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE query_embedding_cache ADD COLUMN IF NOT EXISTS last_hit_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE query_embedding_cache ADD COLUMN IF NOT EXISTS hit_count INTEGER NOT NULL DEFAULT 1;
ALTER TABLE query_embedding_cache ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;
ALTER TABLE query_embedding_cache ADD COLUMN IF NOT EXISTS is_pinned BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE query_embedding_cache ADD COLUMN IF NOT EXISTS query_kind TEXT NOT NULL DEFAULT 'normal';
ALTER TABLE query_embedding_cache ADD COLUMN IF NOT EXISTS task_type TEXT NOT NULL DEFAULT 'RETRIEVAL_QUERY';
ALTER TABLE query_embedding_cache ADD COLUMN IF NOT EXISTS embedding_dim INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_query_embedding_cache_expires_at
ON query_embedding_cache(expires_at)
WHERE is_pinned = FALSE;

CREATE INDEX IF NOT EXISTS idx_query_embedding_cache_normalized_key
ON query_embedding_cache(normalized_key, provider, model, task_type);

CREATE INDEX IF NOT EXISTS idx_query_embedding_cache_canonical_query_hash
ON query_embedding_cache(canonical_query_hash);
