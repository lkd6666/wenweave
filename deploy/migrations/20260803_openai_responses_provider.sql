-- Add the OpenAI Responses API provider protocol to existing MySQL installs.
-- Execute during a short maintenance window after backing up the database.

USE `yibanpaiban`;
SET @schema_name := DATABASE();

SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE `ai_providers` MODIFY COLUMN `provider_type` ENUM(''OPENAI_COMPATIBLE'',''OPENAI_RESPONSES'',''ANTHROPIC'') NOT NULL',
    'SELECT 1'
) INTO @migration_sql
FROM information_schema.columns
WHERE table_schema = @schema_name AND table_name = 'ai_providers' AND column_name = 'provider_type'
  AND column_type NOT LIKE '%OPENAI_RESPONSES%';
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

INSERT INTO `schema_migrations` (`version`)
VALUES ('20260803_openai_responses_provider_v1')
ON DUPLICATE KEY UPDATE `version` = VALUES(`version`);

SHOW COLUMNS FROM `ai_providers` LIKE 'provider_type';
