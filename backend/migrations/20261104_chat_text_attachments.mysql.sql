-- Optional manual DDL; application startup also creates this table.
-- Review against the target schema. Does not modify existing tables.

CREATE TABLE IF NOT EXISTS chat_text_attachments (
	id VARCHAR(36) NOT NULL,
	document_id BIGINT UNSIGNED NOT NULL,
	session_id BIGINT UNSIGNED NOT NULL,
	uploader_id BIGINT UNSIGNED NOT NULL,
	message_id BIGINT UNSIGNED,
	filename VARCHAR(160) NOT NULL,
	size INTEGER NOT NULL,
	characters INTEGER NOT NULL,
	`lines` INTEGER NOT NULL,
	sha256 VARCHAR(64) NOT NULL,
	content LONGTEXT NOT NULL,
	created_at DATETIME NOT NULL DEFAULT now(),
	PRIMARY KEY (id),
	FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE,
	FOREIGN KEY(session_id) REFERENCES chat_sessions (id) ON DELETE CASCADE,
	FOREIGN KEY(uploader_id) REFERENCES users (id) ON DELETE CASCADE,
	FOREIGN KEY(message_id) REFERENCES chat_messages (id) ON DELETE CASCADE
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_unicode_ci

;
CREATE INDEX ix_chat_text_attachments_document_id ON chat_text_attachments (document_id);
CREATE INDEX ix_chat_text_attachments_message_id ON chat_text_attachments (message_id);
CREATE INDEX ix_chat_text_attachments_session_id ON chat_text_attachments (session_id);
CREATE INDEX ix_chat_text_attachments_uploader_id ON chat_text_attachments (uploader_id);
