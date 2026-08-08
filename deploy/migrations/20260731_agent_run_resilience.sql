-- Agent stability migration for MySQL 5.7+ / 8.0+
-- Execute during a short maintenance window after backing up the database.
-- This script is idempotent for the three new agent_runs columns and index.

USE `yibanpaiban`;
SET @schema_name := DATABASE();

-- Existing in-flight runs may already have durable SSE events. Add the
-- allocator cursor when upgrading an older deployment, then synchronize it
-- to the highest existing event sequence so the next append cannot collide.
SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE `agent_runs` ADD COLUMN `event_sequence` INT NOT NULL DEFAULT 0 AFTER `last_progress_at`',
    'SELECT 1'
) INTO @migration_sql
FROM information_schema.columns
WHERE table_schema = @schema_name AND table_name = 'agent_runs' AND column_name = 'event_sequence';
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

UPDATE `agent_runs` AS runs
JOIN (
    SELECT `run_id`, MAX(`sequence`) AS `max_sequence`
    FROM `agent_run_events`
    GROUP BY `run_id`
) AS events ON events.`run_id` = runs.`id`
SET runs.`event_sequence` = GREATEST(COALESCE(runs.`event_sequence`, 0), events.`max_sequence`);

-- Agent run telemetry used to identify the lost worker and its last phase.
SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE `agent_runs` ADD COLUMN `worker_pid` INT NULL AFTER `cancel_requested_at`',
    'SELECT 1'
) INTO @migration_sql
FROM information_schema.columns
WHERE table_schema = @schema_name AND table_name = 'agent_runs' AND column_name = 'worker_pid';
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE `agent_runs` ADD COLUMN `last_phase` VARCHAR(64) NOT NULL DEFAULT '''' AFTER `worker_pid`',
    'SELECT 1'
) INTO @migration_sql
FROM information_schema.columns
WHERE table_schema = @schema_name AND table_name = 'agent_runs' AND column_name = 'last_phase';
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE `agent_runs` ADD COLUMN `last_progress_at` DATETIME(6) NULL AFTER `last_phase`',
    'SELECT 1'
) INTO @migration_sql
FROM information_schema.columns
WHERE table_schema = @schema_name AND table_name = 'agent_runs' AND column_name = 'last_progress_at';
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SELECT IF(
    COUNT(*) = 0,
    'CREATE INDEX `ix_agent_runs_lease_expires_at` ON `agent_runs` (`lease_expires_at`)',
    'SELECT 1'
) INTO @migration_sql
FROM information_schema.statistics
WHERE table_schema = @schema_name AND table_name = 'agent_runs' AND index_name = 'ix_agent_runs_lease_expires_at';
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

-- Preserve old accounting rows while allowing in-flight calls to have no
-- finished_at and making worker-loss visible as abandoned.
ALTER TABLE `model_call_records`
    MODIFY COLUMN `status` ENUM('running','completed','failed','cancelled','abandoned') NOT NULL,
    MODIFY COLUMN `finished_at` DATETIME(6) NULL;

-- The application writes this marker during startup too. Recording it here
-- lets readiness checks pass immediately after the deployment restart.
INSERT INTO `schema_migrations` (`version`)
VALUES ('20260731_agent_run_resilience_v1')
ON DUPLICATE KEY UPDATE `version` = VALUES(`version`);

-- Verification: each result set should contain the expected values.
SHOW COLUMNS FROM `agent_runs` LIKE 'worker_pid';
SHOW COLUMNS FROM `agent_runs` LIKE 'last_phase';
SHOW COLUMNS FROM `agent_runs` LIKE 'last_progress_at';
SHOW COLUMNS FROM `agent_runs` LIKE 'event_sequence';
SHOW COLUMNS FROM `model_call_records` LIKE 'status';
SHOW COLUMNS FROM `model_call_records` LIKE 'finished_at';
SHOW INDEX FROM `agent_runs` WHERE Key_name = 'ix_agent_runs_lease_expires_at';
