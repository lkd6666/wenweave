-- Existing historical attachments retain their message bindings and share bytes.
-- The application bootstrap also applies this migration idempotently.
ALTER TABLE chat_image_attachments DROP INDEX object_key;
CREATE INDEX ix_chat_image_attachments_object_key ON chat_image_attachments (object_key);
