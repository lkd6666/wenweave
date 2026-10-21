ALTER TABLE chat_image_attachments
    ADD COLUMN is_direct_input BOOLEAN NOT NULL DEFAULT 0;

UPDATE chat_image_attachments
SET is_direct_input = 1
WHERE object_key LIKE 'local/chat-images/%'
   OR object_key LIKE 'yibanpaiban/chat-images/%';
