-- migrate:up
-- Immutable canonical source pages for exact citation verification.
CREATE TABLE billshield.source_pages (
 source_key text NOT NULL REFERENCES billshield.source_documents,
 source_page integer NOT NULL CHECK(source_page>0),
 text_original text NOT NULL,
 text_sha256 text NOT NULL CHECK(text_sha256 ~ '^[0-9a-f]{64}$'),
 PRIMARY KEY(source_key,source_page)
);
-- A fresh database is migrated before the runtime login is provisioned.
DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='billshield_app') THEN
  GRANT SELECT ON billshield.source_pages TO billshield_app;
 END IF;
END $$;

-- migrate:down
-- Forward-only: source evidence is retained.
