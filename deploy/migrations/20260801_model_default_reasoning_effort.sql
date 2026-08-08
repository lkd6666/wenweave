-- Model default reasoning effort migration for MySQL 5.7+ / 8.0+
-- Existing models retain their current ``thinking_config.enabled`` behavior.

USE `yibanpaiban`;
SET @schema_name := DATABASE();

SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE `ai_models` ADD COLUMN `default_thinking_effort` VARCHAR(16) NOT NULL DEFAULT ''auto'' AFTER `supports_disabled_thinking`',
    'SELECT 1'
) INTO @migration_sql
FROM information_schema.columns
WHERE table_schema = @schema_name AND table_name = 'ai_models' AND column_name = 'default_thinking_effort';
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

INSERT INTO `schema_migrations` (`version`)
VALUES ('20260801_model_default_reasoning_effort_v1')
ON DUPLICATE KEY UPDATE `version` = VALUES(`version`);

SHOW COLUMNS FROM `ai_models` LIKE 'default_thinking_effort';
