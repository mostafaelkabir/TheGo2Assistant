-- Go2Assistant initial schema.
-- Invariant: every domain table carries tenant_id. Single tenant today; the column
-- is here so multi-tenant later is a default change, not a migration + query audit.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE tenants (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug        text NOT NULL UNIQUE,
    created_at  timestamptz NOT NULL DEFAULT now()
);

INSERT INTO tenants (slug) VALUES ('local');

-- One authorised account on one provider. Holds the incremental-sync cursor:
-- Google Drive startPageToken, or Microsoft Graph deltaLink.
CREATE TABLE connections (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    source       text NOT NULL CHECK (source IN ('gdrive', 'onedrive')),
    account      text NOT NULL,
    token_blob   bytea NOT NULL,          -- Fernet-encrypted OAuth credentials
    cursor       text,
    synced_at    timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, source, account)
);

CREATE TYPE doc_status AS ENUM ('pending', 'extracting', 'indexed', 'failed', 'skipped');

CREATE TABLE documents (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    connection_id  uuid NOT NULL REFERENCES connections(id) ON DELETE CASCADE,
    source         text NOT NULL,
    external_id    text NOT NULL,
    title          text NOT NULL,
    path           text NOT NULL DEFAULT '',
    mime           text NOT NULL DEFAULT '',
    web_url        text,
    size_bytes     bigint,
    modified_at    timestamptz,
    content_hash   text,
    status         doc_status NOT NULL DEFAULT 'pending',
    error          text,
    indexed_at     timestamptz,
    created_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, source, external_id)
);

CREATE INDEX documents_tenant_status_idx ON documents (tenant_id, status);
CREATE INDEX documents_modified_idx      ON documents (tenant_id, modified_at DESC);
CREATE INDEX documents_title_trgm_idx    ON documents USING gin (title gin_trgm_ops);

-- Extraction is expensive (OCR especially). Key the cache by content hash so a file
-- that is renamed, moved, or re-synced unchanged is never re-extracted.
CREATE TABLE extraction_cache (
    content_hash  text PRIMARY KEY,
    extractor     text NOT NULL,
    payload       jsonb NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE chunks (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    document_id   uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal       int NOT NULL,
    text          text NOT NULL,
    embedding     vector(1024),
    page          int,
    sheet         text,
    slide         int,
    heading       text,
    -- 'simple' rather than 'english' or 'arabic': the corpus is mixed, and stemming
    -- with the wrong language config is worse than not stemming at all.
    tsv           tsvector GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED,
    UNIQUE (document_id, ordinal)
);

CREATE INDEX chunks_tenant_idx ON chunks (tenant_id);
CREATE INDEX chunks_tsv_idx    ON chunks USING gin (tsv);
CREATE INDEX chunks_vec_idx    ON chunks USING hnsw (embedding vector_cosine_ops);

-- Postgres-backed queue. Workers claim with FOR UPDATE SKIP LOCKED; no Redis.
CREATE TYPE job_status AS ENUM ('queued', 'running', 'done', 'failed');

CREATE TABLE jobs (
    id            bigserial PRIMARY KEY,
    tenant_id     uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    kind          text NOT NULL,
    payload       jsonb NOT NULL DEFAULT '{}'::jsonb,
    status        job_status NOT NULL DEFAULT 'queued',
    attempts      int NOT NULL DEFAULT 0,
    last_error    text,
    run_after     timestamptz NOT NULL DEFAULT now(),
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX jobs_claim_idx ON jobs (status, run_after) WHERE status = 'queued';
