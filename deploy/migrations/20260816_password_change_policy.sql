ALTER TABLE users
    ADD COLUMN password_change_required BOOL NOT NULL DEFAULT 0;
