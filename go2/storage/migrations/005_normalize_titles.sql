-- Titles arrived in whatever Unicode form the source used. macOS hands over
-- decomposed (NFD) filenames, so an Arabic title stored from disk does not
-- equal the same name typed into a query, and `title_contains` silently
-- returns nothing. Ingestion now normalises on the way in; this brings rows
-- written before that to the same form.
UPDATE documents
   SET title = normalize(title, NFC)
 WHERE title IS DISTINCT FROM normalize(title, NFC);
