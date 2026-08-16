-- Operational availability switches for providers and their text/image models.
-- Existing records remain enabled so this migration preserves prior behavior.

USE `yibanpaiban`;
SET @schema_name := DATABASE();

SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE `ai_providers` ADD COLUMN `is_enabled` BOOLEAN NOT NULL DEFAULT 1 AFTER `image_base_url`',
    'SELECT 1'
) INTO @migration_sql
FROM information_schema.columns
WHERE table_schema = @schema_name AND table_name = 'ai_providers' AND column_name = 'is_enabled';
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE `ai_models` ADD COLUMN `is_enabled` BOOLEAN NOT NULL DEFAULT 1 AFTER `is_default`',
    'SELECT 1'
) INTO @migration_sql
FROM information_schema.columns
WHERE table_schema = @schema_name AND table_name = 'ai_models' AND column_name = 'is_enabled';
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE `ai_image_models` ADD COLUMN `is_enabled` BOOLEAN NOT NULL DEFAULT 1 AFTER `is_default`',
    'SELECT 1'
) INTO @migration_sql
FROM information_schema.columns
WHERE table_schema = @schema_name AND table_name = 'ai_image_models' AND column_name = 'is_enabled';
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

INSERT INTO `schema_migrations` (`version`)
VALUES ('20260813_model_provider_enablement_v1')
ON DUPLICATE KEY UPDATE `version` = VALUES(`version`);

SHOW COLUMNS FROM `ai_providers` LIKE 'is_enabled';
SHOW COLUMNS FROM `ai_models` LIKE 'is_enabled';
SHOW COLUMNS FROM `ai_image_models` LIKE 'is_enabled';
