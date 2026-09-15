-- Add the native Google Gemini provider protocol and migrate only the bundled
-- Google OpenAI-compatible endpoint. Custom gateways are intentionally left
-- untouched.
USE `yibanpaiban`;
SET @schema_name := DATABASE();

SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE `ai_providers` MODIFY COLUMN `provider_type` ENUM(''OPENAI_COMPATIBLE'',''OPENAI_RESPONSES'',''ANTHROPIC'',''GEMINI_NATIVE'') NOT NULL',
    'SELECT 1'
) INTO @migration_sql
FROM information_schema.columns
WHERE table_schema = @schema_name AND table_name = 'ai_providers' AND column_name = 'provider_type'
  AND column_type NOT LIKE '%GEMINI_NATIVE%';
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

UPDATE `ai_providers`
SET provider_type = 'GEMINI_NATIVE',
    base_url = 'https://generativelanguage.googleapis.com/v1beta'
WHERE provider_type = 'OPENAI_COMPATIBLE'
  AND RTRIM(base_url) = 'https://generativelanguage.googleapis.com/v1beta/openai';

INSERT INTO `schema_migrations` (`version`)
VALUES ('20260825_gemini_native_provider_v1')
ON DUPLICATE KEY UPDATE `version` = VALUES(`version`);
