-- Rozszerzenie istniejącej tabeli forum. Do ręcznego uruchomienia po przeglądzie.
-- Wykonać jednokrotnie, po utworzeniu tabeli przez forum_entenda_uat_db.sql.
-- Dotychczasowe wpisy zachowują NULL: wiadomość do wszystkich, bez odpowiedzi.
USE `entenda_uat_db`;

ALTER TABLE `game_forum_messages`
    ADD COLUMN `recipient_user_id` INT NULL,
    ADD COLUMN `recipient_name` VARCHAR(50) NULL,
    ADD COLUMN `recipient_country_name` VARCHAR(255) NULL,
    ADD COLUMN `recipient_flag_path` VARCHAR(512) NULL,
    ADD COLUMN `reply_to_id` INT NULL,
    ADD KEY `ix_forum_recipient` (`recipient_user_id`),
    ADD KEY `ix_forum_reply` (`reply_to_id`),
    ADD CONSTRAINT `fk_forum_recipient` FOREIGN KEY (`recipient_user_id`)
        REFERENCES `game_users` (`id`) ON DELETE RESTRICT,
    ADD CONSTRAINT `fk_forum_reply` FOREIGN KEY (`reply_to_id`)
        REFERENCES `game_forum_messages` (`id`) ON DELETE RESTRICT;
