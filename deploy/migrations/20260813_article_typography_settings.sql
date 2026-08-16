-- Global defaults for AI-generated article body typography.

USE `yibanpaiban`;

CREATE TABLE IF NOT EXISTS `article_typography_settings` (
    `id` BIGINT UNSIGNED NOT NULL,
    `horizontal_padding_px` FLOAT NOT NULL DEFAULT 4,
    `paragraph_spacing_px` FLOAT NOT NULL DEFAULT 20,
    `font_size_px` FLOAT NOT NULL DEFAULT 15,
    `line_height_em` FLOAT NOT NULL DEFAULT 2,
    `letter_spacing_px` FLOAT NOT NULL DEFAULT 1,
    `text_indent_em` FLOAT NOT NULL DEFAULT 2,
    `text_color` VARCHAR(7) NOT NULL DEFAULT '#000000',
    `updated_by_id` BIGINT UNSIGNED NULL,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    CONSTRAINT `fk_article_typography_settings_updated_by` FOREIGN KEY (`updated_by_id`)
        REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO `article_typography_settings` (
    `id`, `horizontal_padding_px`, `paragraph_spacing_px`, `font_size_px`,
    `line_height_em`, `letter_spacing_px`, `text_indent_em`, `text_color`
) VALUES (1, 4, 20, 15, 2, 1, 2, '#000000')
ON DUPLICATE KEY UPDATE `id` = VALUES(`id`);

INSERT INTO `schema_migrations` (`version`)
VALUES ('20260813_article_typography_settings_v1')
ON DUPLICATE KEY UPDATE `version` = VALUES(`version`);
