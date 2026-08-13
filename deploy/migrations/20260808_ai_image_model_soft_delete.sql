-- Keep image models referenced by historical generations while hiding them
-- from all active model selectors.
USE `yibanpaiban`;
SET @schema_name := DATABASE();

SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE `ai_image_models` ADD COLUMN `deleted_at` DATETIME NULL',
    'SELECT 1'
) INTO @migration_sql
FROM information_schema.columns
WHERE table_schema = @schema_name AND table_name = 'ai_image_models' AND column_name = 'deleted_at';
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE `ai_image_models` ADD KEY `ix_ai_image_models_deleted_at` (`deleted_at`)',
    'SELECT 1'
) INTO @migration_sql
FROM information_schema.statistics
WHERE table_schema = @schema_name AND table_name = 'ai_image_models' AND index_name = 'ix_ai_image_models_deleted_at';
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

INSERT INTO `schema_migrations` (`version`)
VALUES ('20260808_ai_image_model_soft_delete_v1')
ON DUPLICATE KEY UPDATE `version` = VALUES(`version`);

SHOW COLUMNS FROM `ai_image_models` LIKE 'deleted_at';
