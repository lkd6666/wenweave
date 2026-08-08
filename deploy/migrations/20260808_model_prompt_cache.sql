-- Explicit OpenAI prompt-cache controls are opt-in per model. Existing models
-- retain their current request shape until an administrator enables the flag.

USE `yibanpaiban`;
SET @schema_name := DATABASE();

SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE `ai_models` ADD COLUMN `prompt_cache_enabled` BOOLEAN NOT NULL DEFAULT 0',
    'SELECT 1'
) INTO @migration_sql
FROM information_schema.columns
WHERE table_schema = @schema_name AND table_name = 'ai_models' AND column_name = 'prompt_cache_enabled';
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

INSERT INTO `schema_migrations` (`version`)
VALUES ('20260808_model_prompt_cache_v1')
ON DUPLICATE KEY UPDATE `version` = VALUES(`version`);

SHOW COLUMNS FROM `ai_models` LIKE 'prompt_cache_enabled';
