-- Persist a per-task generation deadline. Existing tasks keep the previous
-- three-minute behavior.
ALTER TABLE image_generations
  ADD COLUMN timeout_seconds INT NOT NULL DEFAULT 180 AFTER quality;
