-- Indexes used by the shared pending-question notifier and lease recovery.
-- The bootstrap migration also creates these idempotently during application startup.
SET @schema_name := DATABASE();

SET @migration_sql := IF(
  EXISTS(
    SELECT 1 FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'agent_runs'
      AND INDEX_NAME = 'ix_agent_runs_status_lease'
  ),
  'SELECT 1',
  'CREATE INDEX ix_agent_runs_status_lease ON agent_runs (status, lease_expires_at)'
);
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @migration_sql := IF(
  EXISTS(
    SELECT 1 FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'chat_layout_references'
      AND COLUMN_NAME = 'preview_token_encrypted'
  ),
  'SELECT 1',
  'ALTER TABLE chat_layout_references ADD COLUMN preview_token_encrypted VARCHAR(512) NULL'
);
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @migration_sql := IF(
  EXISTS(
    SELECT 1 FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'chat_user_questions'
      AND INDEX_NAME = 'ix_chat_user_questions_user_status_created'
  ),
  'SELECT 1',
  'CREATE INDEX ix_chat_user_questions_user_status_created ON chat_user_questions (user_id, status, created_at)'
);
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

INSERT INTO schema_migrations (version)
VALUES ('20260921_runtime_performance_indexes_v1')
ON DUPLICATE KEY UPDATE version = VALUES(version);
