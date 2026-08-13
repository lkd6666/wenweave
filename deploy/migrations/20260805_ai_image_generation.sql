-- AI image generation: provider image endpoint and durable image tables.
-- Existing providers reuse their encrypted API key; empty image fields mean
-- that image generation is not configured.
SET @schema_name = DATABASE();

SET @sql = IF(
  EXISTS(SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = @schema_name AND TABLE_NAME = 'ai_providers' AND COLUMN_NAME = 'image_protocol'),
  'SELECT 1',
  'ALTER TABLE `ai_providers` ADD COLUMN `image_protocol` VARCHAR(48) NOT NULL DEFAULT '''' AFTER `base_url`, ADD COLUMN `image_base_url` VARCHAR(512) NOT NULL DEFAULT '''' AFTER `image_protocol`'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

CREATE TABLE IF NOT EXISTS `ai_image_models` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `provider_id` BIGINT UNSIGNED NOT NULL,
  `model_name` VARCHAR(256) NOT NULL,
  `display_name` VARCHAR(256) NOT NULL,
  `description` VARCHAR(1024) NOT NULL DEFAULT '',
  `supported_aspect_ratios` JSON NOT NULL,
  `supported_qualities` JSON NOT NULL,
  `is_default` BOOLEAN NOT NULL DEFAULT 0,
  `access_mode` VARCHAR(16) NOT NULL DEFAULT 'all',
  `adapter_config` JSON NOT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `deleted_at` DATETIME NULL,
  PRIMARY KEY (`id`),
  KEY `ix_ai_image_models_provider_id` (`provider_id`),
  KEY `ix_ai_image_models_deleted_at` (`deleted_at`),
  CONSTRAINT `fk_ai_image_models_provider` FOREIGN KEY (`provider_id`) REFERENCES `ai_providers` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

SET @sql = IF(
  EXISTS(SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = @schema_name AND TABLE_NAME = 'ai_image_models')
    AND NOT EXISTS(SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = @schema_name AND TABLE_NAME = 'ai_image_models' AND COLUMN_NAME = 'deleted_at'),
  'ALTER TABLE `ai_image_models` ADD COLUMN `deleted_at` DATETIME NULL, ADD KEY `ix_ai_image_models_deleted_at` (`deleted_at`)',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

CREATE TABLE IF NOT EXISTS `image_model_user_access` (
  `model_id` BIGINT UNSIGNED NOT NULL,
  `user_id` BIGINT UNSIGNED NOT NULL,
  PRIMARY KEY (`model_id`, `user_id`),
  CONSTRAINT `fk_image_model_user_access_model` FOREIGN KEY (`model_id`) REFERENCES `ai_image_models` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_image_model_user_access_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `image_model_group_access` (
  `model_id` BIGINT UNSIGNED NOT NULL,
  `group_id` BIGINT UNSIGNED NOT NULL,
  PRIMARY KEY (`model_id`, `group_id`),
  CONSTRAINT `fk_image_model_group_access_model` FOREIGN KEY (`model_id`) REFERENCES `ai_image_models` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_image_model_group_access_group` FOREIGN KEY (`group_id`) REFERENCES `user_groups` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `image_generations` (
  `id` VARCHAR(36) NOT NULL,
  `document_id` BIGINT UNSIGNED NOT NULL,
  `session_id` BIGINT UNSIGNED NULL,
  `model_id` BIGINT UNSIGNED NOT NULL,
  `user_id` BIGINT UNSIGNED NOT NULL,
  `source` ENUM('editor','agent') NOT NULL,
  `purpose` ENUM('cover','body') NOT NULL,
  `prompt` LONGTEXT NOT NULL,
  `quantity` INT NOT NULL DEFAULT 1,
  `aspect_ratio` VARCHAR(24) NOT NULL DEFAULT 'landscape',
  `quality` VARCHAR(24) NOT NULL DEFAULT 'auto',
  `anchor_block_id` VARCHAR(128) NOT NULL DEFAULT '',
  `direct_insert` BOOLEAN NOT NULL DEFAULT 0,
  `provider_task_id` VARCHAR(256) NOT NULL DEFAULT '',
  `status` ENUM('pending','running','succeeded','failed','cancelled') NOT NULL DEFAULT 'pending',
  `cancel_requested` BOOLEAN NOT NULL DEFAULT 0,
  `usage_json` LONGTEXT NOT NULL,
  `error_message` VARCHAR(2048) NOT NULL DEFAULT '',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `finished_at` DATETIME NULL,
  PRIMARY KEY (`id`),
  KEY `ix_image_generations_document_id` (`document_id`),
  KEY `ix_image_generations_status` (`status`),
  CONSTRAINT `fk_image_generations_document` FOREIGN KEY (`document_id`) REFERENCES `documents` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_image_generations_session` FOREIGN KEY (`session_id`) REFERENCES `chat_sessions` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_image_generations_model` FOREIGN KEY (`model_id`) REFERENCES `ai_image_models` (`id`) ON DELETE RESTRICT,
  CONSTRAINT `fk_image_generations_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `generated_image_assets` (
  `id` VARCHAR(36) NOT NULL,
  `generation_id` VARCHAR(36) NOT NULL,
  `object_key` VARCHAR(512) NOT NULL,
  `storage_mode` VARCHAR(12) NOT NULL,
  `url` VARCHAR(4096) NOT NULL,
  `content_type` VARCHAR(64) NOT NULL,
  `size` INT NOT NULL,
  `width` INT NOT NULL DEFAULT 0,
  `height` INT NOT NULL DEFAULT 0,
  `revised_prompt` LONGTEXT NOT NULL,
  `is_applied` BOOLEAN NOT NULL DEFAULT 0,
  `applied_at` DATETIME NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_generated_image_assets_object_key` (`object_key`),
  KEY `ix_generated_image_assets_generation_id` (`generation_id`),
  CONSTRAINT `fk_generated_image_assets_generation` FOREIGN KEY (`generation_id`) REFERENCES `image_generations` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

SET @sql = IF(
  EXISTS(SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = @schema_name AND TABLE_NAME = 'chat_sessions' AND COLUMN_NAME = 'image_model_id'),
  'SELECT 1',
  'ALTER TABLE `chat_sessions` ADD COLUMN `image_model_id` BIGINT NULL, ADD COLUMN `auto_image_generation_enabled` BOOLEAN NOT NULL DEFAULT 0'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
