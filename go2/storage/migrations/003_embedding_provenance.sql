-- Vectors from different embedding models are not comparable. Mixing them is
-- silent: queries return confident nonsense rather than an error. Recording
-- which model produced a document's vectors lets search scope itself to the
-- model currently configured, so switching providers degrades to "nothing
-- indexed yet" instead of to garbage.

ALTER TABLE documents ADD COLUMN embedding_model text;

-- Everything indexed so far came from the local Qwen3 model.
UPDATE documents SET embedding_model = 'electroglyph/Qwen3-Embedding-0.6B-onnx-uint8'
 WHERE embedding_model IS NULL;

CREATE INDEX documents_embedding_model_idx ON documents (tenant_id, embedding_model);
