ALTER TABLE layout_capture_sessions
    ADD COLUMN purpose VARCHAR(32) NOT NULL DEFAULT 'layout_reference' AFTER canonical_url;
