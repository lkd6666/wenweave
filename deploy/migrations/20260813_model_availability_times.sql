-- Daily China Standard Time availability schedules for providers and models.
-- Empty JSON arrays preserve the existing all-day availability behavior.

USE `yibanpaiban`;
SET @schema_name := DATABASE();

SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE `ai_providers` ADD COLUMN `availability_time_ranges` JSON NULL AFTER `is_enabled`',
    'SELECT 1'
) INTO @migration_sql
FROM information_schema.columns
WHERE table_schema = @schema_name AND table_name = 'ai_providers' AND column_name = 'availability_time_ranges';
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;
UPDATE `ai_providers` SET `availability_time_ranges` = JSON_ARRAY() WHERE `availability_time_ranges` IS NULL;
ALTER TABLE `ai_providers` MODIFY COLUMN `availability_time_ranges` JSON NOT NULL;

SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE `ai_models` ADD COLUMN `availability_time_ranges` JSON NULL AFTER `is_enabled`',
    'SELECT 1'
) INTO @migration_sql
FROM information_schema.columns
WHERE table_schema = @schema_name AND table_name = 'ai_models' AND column_name = 'availability_time_ranges';
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;
UPDATE `ai_models` SET `availability_time_ranges` = JSON_ARRAY() WHERE `availability_time_ranges` IS NULL;
ALTER TABLE `ai_models` MODIFY COLUMN `availability_time_ranges` JSON NOT NULL;

SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE `ai_image_models` ADD COLUMN `availability_time_ranges` JSON NULL AFTER `is_enabled`',
    'SELECT 1'
) INTO @migration_sql
FROM information_schema.columns
WHERE table_schema = @schema_name AND table_name = 'ai_image_models' AND column_name = 'availability_time_ranges';
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;
UPDATE `ai_image_models` SET `availability_time_ranges` = JSON_ARRAY() WHERE `availability_time_ranges` IS NULL;
ALTER TABLE `ai_image_models` MODIFY COLUMN `availability_time_ranges` JSON NOT NULL;

INSERT INTO `schema_migrations` (`version`)
VALUES ('20260813_model_availability_times_v1')
ON DUPLICATE KEY UPDATE `version` = VALUES(`version`);

SHOW COLUMNS FROM `ai_providers` LIKE 'availability_time_ranges';
SHOW COLUMNS FROM `ai_models` LIKE 'availability_time_ranges';
SHOW COLUMNS FROM `ai_image_models` LIKE 'availability_time_ranges';
