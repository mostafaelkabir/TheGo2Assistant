-- What a picker (T-013) put in scope for a connection.
--
-- drive.file grants nothing until the user picks it, and the pick itself is
-- provider-side state Google holds, not this database's. This table is our
-- own record of what was picked, kept for two things Google's grant alone
-- cannot do: let a sync stop honouring a pick without revoking it (removed_at,
-- a soft stop -- already-indexed documents are untouched, only future syncs
-- change), and let a picked folder's contents be re-expanded on every sync
-- rather than frozen at pick time, so a file added to the folder later is
-- synced without picking again.
--
-- Deliberately provider-neutral: keyed on connection_id and an opaque
-- external_id, the same shape any second connector's picker would write.

CREATE TABLE drive_selections (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    connection_id  uuid NOT NULL REFERENCES connections(id) ON DELETE CASCADE,
    external_id    text NOT NULL,
    kind           text NOT NULL CHECK (kind IN ('file', 'folder')),
    title          text NOT NULL DEFAULT '',
    removed_at     timestamptz,
    created_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (connection_id, external_id)
);

CREATE INDEX drive_selections_active_idx ON drive_selections (connection_id)
    WHERE removed_at IS NULL;
