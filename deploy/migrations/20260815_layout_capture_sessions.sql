CREATE TABLE IF NOT EXISTS layout_capture_sessions (
    id VARCHAR(36) NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    canonical_url VARCHAR(2048) NOT NULL,
    purpose VARCHAR(32) NOT NULL DEFAULT 'layout_reference',
    token_hash VARCHAR(64) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    expires_at DATETIME NOT NULL,
    consumed_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT fk_layout_capture_sessions_user
        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    INDEX ix_layout_capture_sessions_user_id (user_id),
    INDEX ix_layout_capture_sessions_expires_at (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
