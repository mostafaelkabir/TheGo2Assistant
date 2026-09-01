-- Local uploads are a first-class source: the working agreement requires every
-- source to share one ingestion pipeline, so 'upload' belongs alongside the
-- connectors rather than in a parallel path.

ALTER TABLE connections DROP CONSTRAINT connections_source_check;
ALTER TABLE connections ADD CONSTRAINT connections_source_check
    CHECK (source IN ('gdrive', 'onedrive', 'upload'));
