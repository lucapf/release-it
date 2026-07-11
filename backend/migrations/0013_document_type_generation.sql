-- Document types are either manually uploaded or generated from a prompt.
--
-- * kind — 'manual' (the operator uploads the file) or 'generated' (the document
--   is built by the system). Existing rows default to 'manual', preserving the
--   current behaviour where every type is uploaded by hand.
-- * generation_prompt — for a 'generated' type, the instructions describing how
--   the document must be built. Empty for manual types (and cleared whenever a
--   type is switched back to manual).
ALTER TABLE document_type
    ADD COLUMN kind TEXT NOT NULL DEFAULT 'manual'
    CHECK (kind IN ('manual', 'generated'));

ALTER TABLE document_type
    ADD COLUMN generation_prompt TEXT NOT NULL DEFAULT '';
