-- Reusable image library and the global personal/shared visibility mode.

CREATE TABLE IF NOT EXISTS `image_library_settings` (
  `id` BIGINT UNSIGNED NOT NULL,
  `mode` VARCHAR(16) NOT NULL DEFAULT 'personal',
  `updated_by_id` BIGINT UNSIGNED NULL,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  CONSTRAINT `fk_image_library_settings_updated_by` FOREIGN KEY (`updated_by_id`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT IGNORE INTO `image_library_settings` (`id`, `mode`) VALUES (1, 'personal');

CREATE TABLE IF NOT EXISTS `image_library_assets` (
  `id` VARCHAR(36) NOT NULL,
  `owner_id` BIGINT UNSIGNED NOT NULL,
  `document_id` BIGINT UNSIGNED NULL,
  `generation_id` VARCHAR(36) NOT NULL DEFAULT '',
  `generated_asset_id` VARCHAR(36) NOT NULL DEFAULT '',
  `name` VARCHAR(256) NOT NULL DEFAULT '图片',
  `source` VARCHAR(16) NOT NULL DEFAULT 'upload',
  `object_key` VARCHAR(512) NOT NULL,
  `storage_mode` VARCHAR(12) NOT NULL,
  `url` VARCHAR(4096) NOT NULL,
  `content_type` VARCHAR(64) NOT NULL,
  `size` INT NOT NULL,
  `width` INT NOT NULL DEFAULT 0,
  `height` INT NOT NULL DEFAULT 0,
  `is_shared` BOOLEAN NOT NULL DEFAULT 0,
  `deleted_at` DATETIME NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_image_library_assets_object_key` (`object_key`),
  KEY `ix_image_library_assets_owner_id` (`owner_id`),
  KEY `ix_image_library_assets_document_id` (`document_id`),
  KEY `ix_image_library_assets_generation_id` (`generation_id`),
  KEY `ix_image_library_assets_generated_asset_id` (`generated_asset_id`),
  KEY `ix_image_library_assets_is_shared` (`is_shared`),
  KEY `ix_image_library_assets_deleted_at` (`deleted_at`),
  CONSTRAINT `fk_image_library_assets_owner` FOREIGN KEY (`owner_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_image_library_assets_document` FOREIGN KEY (`document_id`) REFERENCES `documents` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

SET @sql = IF(
  EXISTS(SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'image_library_assets')
    AND NOT EXISTS(SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'image_library_assets' AND COLUMN_NAME = 'is_shared'),
  'ALTER TABLE `image_library_assets` ADD COLUMN `is_shared` BOOLEAN NOT NULL DEFAULT 0, ADD KEY `ix_image_library_assets_is_shared` (`is_shared`)',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
  EXISTS(SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'image_library_assets')
    AND NOT EXISTS(SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'image_library_assets' AND COLUMN_NAME = 'deleted_at'),
  'ALTER TABLE `image_library_assets` ADD COLUMN `deleted_at` DATETIME NULL, ADD KEY `ix_image_library_assets_deleted_at` (`deleted_at`)',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
  EXISTS(SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'image_library_assets')
    AND NOT EXISTS(SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'image_library_assets' AND COLUMN_NAME = 'updated_at'),
  'ALTER TABLE `image_library_assets` ADD COLUMN `updated_at` DATETIME NULL',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

UPDATE `image_library_assets` SET `updated_at` = `created_at` WHERE `updated_at` IS NULL;

ALTER TABLE `image_library_assets`
  MODIFY COLUMN `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP;
