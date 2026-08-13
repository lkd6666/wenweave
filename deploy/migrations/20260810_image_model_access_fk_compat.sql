-- Repair legacy parent-table engines before image model access tables are
-- created. Run this migration before restarting the backend after upgrade.
SET @schema_name := DATABASE();

SET @migration_sql := IF(
  EXISTS(SELECT 1 FROM information_schema.tables WHERE table_schema = @schema_name AND table_name = 'ai_image_models' AND engine <> 'InnoDB'),
  'ALTER TABLE `ai_image_models` ENGINE=InnoDB',
  'SELECT 1'
);
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @migration_sql := IF(
  EXISTS(SELECT 1 FROM information_schema.tables WHERE table_schema = @schema_name AND table_name = 'users' AND engine <> 'InnoDB'),
  'ALTER TABLE `users` ENGINE=InnoDB',
  'SELECT 1'
);
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @migration_sql := IF(
  EXISTS(SELECT 1 FROM information_schema.tables WHERE table_schema = @schema_name AND table_name = 'user_groups' AND engine <> 'InnoDB'),
  'ALTER TABLE `user_groups` ENGINE=InnoDB',
  'SELECT 1'
);
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @image_model_id_type := NULL;
SET @user_id_type := NULL;
SET @group_id_type := NULL;
SELECT column_type INTO @image_model_id_type
FROM information_schema.columns
WHERE table_schema = @schema_name AND table_name = 'ai_image_models' AND column_name = 'id';
SELECT column_type INTO @user_id_type
FROM information_schema.columns
WHERE table_schema = @schema_name AND table_name = 'users' AND column_name = 'id';
SELECT column_type INTO @group_id_type
FROM information_schema.columns
WHERE table_schema = @schema_name AND table_name = 'user_groups' AND column_name = 'id';

SET @migration_sql := IF(
  @image_model_id_type IS NOT NULL AND @user_id_type IS NOT NULL
    AND NOT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_schema = @schema_name AND table_name = 'image_model_user_access'),
  CONCAT(
    'CREATE TABLE `image_model_user_access` (`model_id` ', @image_model_id_type,
    ' NOT NULL, `user_id` ', @user_id_type,
    ' NOT NULL, PRIMARY KEY (`model_id`, `user_id`), ',
    'CONSTRAINT `fk_image_model_user_access_model` FOREIGN KEY (`model_id`) REFERENCES `ai_image_models` (`id`) ON DELETE CASCADE, ',
    'CONSTRAINT `fk_image_model_user_access_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4'
  ),
  'SELECT 1'
);
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @migration_sql := IF(
  @image_model_id_type IS NOT NULL AND @group_id_type IS NOT NULL
    AND NOT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_schema = @schema_name AND table_name = 'image_model_group_access'),
  CONCAT(
    'CREATE TABLE `image_model_group_access` (`model_id` ', @image_model_id_type,
    ' NOT NULL, `group_id` ', @group_id_type,
    ' NOT NULL, PRIMARY KEY (`model_id`, `group_id`), ',
    'CONSTRAINT `fk_image_model_group_access_model` FOREIGN KEY (`model_id`) REFERENCES `ai_image_models` (`id`) ON DELETE CASCADE, ',
    'CONSTRAINT `fk_image_model_group_access_group` FOREIGN KEY (`group_id`) REFERENCES `user_groups` (`id`) ON DELETE CASCADE) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4'
  ),
  'SELECT 1'
);
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

INSERT INTO `schema_migrations` (`version`)
VALUES ('20260810_image_model_access_fk_compat_v1')
ON DUPLICATE KEY UPDATE `version` = VALUES(`version`);
