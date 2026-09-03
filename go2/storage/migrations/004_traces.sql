-- Observability for the retrieval path.
--
-- Application logs record that a request arrived and a response left. They do
-- not record which component did what to the data in between, so when an
-- answer is wrong there is nothing to inspect. These two tables record the
-- per-component steps: what went in, what came out, how long it took, and --
-- the question specific to this system -- whether that step sent anything off
-- the machine.
--
-- Inputs and outputs are stored as summaries and counts, never raw passage
-- text. A trace log that quietly becomes a second copy of the corpus is a
-- liability, not a diagnostic.

CREATE TABLE traces (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    kind         text NOT NULL,
    label        text NOT NULL DEFAULT '',
    outcome      text,
    duration_ms  double precision,
    meta         jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX traces_recent_idx ON traces (tenant_id, created_at DESC);

CREATE TABLE trace_steps (
    id           bigserial PRIMARY KEY,
    trace_id     uuid NOT NULL REFERENCES traces(id) ON DELETE CASCADE,
    ordinal      int NOT NULL,
    component    text NOT NULL,
    duration_ms  double precision NOT NULL,
    -- Whether this step sent data to a third party. The single most important
    -- column here: it turns "what leaves the machine" from a claim in a README
    -- into something you can query.
    egress       boolean NOT NULL DEFAULT false,
    input        jsonb NOT NULL DEFAULT '{}'::jsonb,
    output       jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (trace_id, ordinal)
);
