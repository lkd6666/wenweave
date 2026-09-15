-- Agent run ownership and event sequence allocation rely on row locks.
-- Imported databases may have these tables as MyISAM, where FOR UPDATE is
-- ignored and concurrent workers can steal leases or collide on sequences.
SET @schema_name := DATABASE();

SET @table_engine := (
  SELECT ENGINE FROM information_schema.TABLES
  WHERE TABLE_SCHEMA = @schema_name AND TABLE_NAME = 'agent_runs'
);
SET @migration_sql := IF(
  @table_engine IS NOT NULL AND @table_engine <> 'InnoDB',
  'ALTER TABLE `agent_runs` ENGINE=InnoDB',
  'SELECT 1'
);
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @table_engine := (
  SELECT ENGINE FROM information_schema.TABLES
  WHERE TABLE_SCHEMA = @schema_name AND TABLE_NAME = 'agent_run_events'
);
SET @migration_sql := IF(
  @table_engine IS NOT NULL AND @table_engine <> 'InnoDB',
  'ALTER TABLE `agent_run_events` ENGINE=InnoDB',
  'SELECT 1'
);
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

INSERT INTO `schema_migrations` (`version`)
VALUES ('20260819_agent_run_lock_engine_v1')
ON DUPLICATE KEY UPDATE `version` = VALUES(`version`);
