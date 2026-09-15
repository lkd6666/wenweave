-- WeChat permits article titles up to 64 characters. Preserve existing rows
-- while widening draft-history records created by earlier versions.
SET @schema_name := DATABASE();
SET @column_length := (
  SELECT CHARACTER_MAXIMUM_LENGTH
  FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'wechat_drafts'
    AND COLUMN_NAME = 'article_title'
);
SET @migration_sql := IF(
  @column_length IS NOT NULL AND @column_length < 64,
  CONCAT('ALTER TABLE `wechat_drafts` MODIFY COLUMN `article_title` VARCHAR(64) NOT NULL DEFAULT ', QUOTE('')),
  'SELECT 1'
);
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

INSERT INTO `schema_migrations` (`version`)
VALUES ('20260822_wechat_draft_title_64_v1')
ON DUPLICATE KEY UPDATE `version` = VALUES(`version`);
