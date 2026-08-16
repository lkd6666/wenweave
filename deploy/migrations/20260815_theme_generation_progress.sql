ALTER TABLE gzh_theme_generations
    ADD COLUMN progress_stage VARCHAR(32) NOT NULL DEFAULT 'pending',
    ADD COLUMN progress_current INT NOT NULL DEFAULT 0,
    ADD COLUMN progress_total INT NOT NULL DEFAULT 0,
    ADD COLUMN progress_message VARCHAR(256) NOT NULL DEFAULT '';
