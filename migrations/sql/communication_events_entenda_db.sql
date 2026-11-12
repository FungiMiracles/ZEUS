-- Powiadomienia generatora i prywatna komunikacja. Uruchomić jednokrotnie.
-- Wymaga wcześniejszego skryptu diplomacy_entenda_db.sql.
-- Nie tworzy zaległych powiadomień i nie zmienia danych zdarzeń ani stosunków.
USE `entenda_db`;

CREATE TABLE `game_generated_event_snapshots` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `source_event_id` INT NOT NULL,
    `country_id` INT NOT NULL,
    `country_name` VARCHAR(255) NOT NULL,
    `region_name` VARCHAR(255) NOT NULL,
    `event_type` VARCHAR(64) NOT NULL,
    `content` TEXT NOT NULL,
    `effects` JSON NOT NULL,
    `entenda_date` DATETIME NULL,
    `created_at` DATETIME NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_generated_event_source` (`source_event_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Brak klucza obcego do zdarzenia: kopia przetrwa retencję generatora.
ALTER TABLE `game_notifications`
    DROP CHECK `ck_notification_target`,
    ADD COLUMN `generated_event_id` INT NULL,
    ADD UNIQUE KEY `uq_notification_user_event` (`user_id`, `generated_event_id`),
    ADD KEY `ix_notification_event` (`generated_event_id`),
    ADD CONSTRAINT `fk_notification_event` FOREIGN KEY (`generated_event_id`)
        REFERENCES `game_generated_event_snapshots` (`id`) ON DELETE RESTRICT,
    ADD CONSTRAINT `ck_notification_target` CHECK (
        (`notification_type` = 'FORUM_MESSAGE' AND `message_id` IS NOT NULL
         AND `diplomatic_action_id` IS NULL AND `generated_event_id` IS NULL)
        OR
        (`notification_type` = 'DIPLOMACY' AND `diplomatic_action_id` IS NOT NULL
         AND `message_id` IS NULL AND `generated_event_id` IS NULL)
        OR
        (`notification_type` = 'GENERATED_EVENT' AND `generated_event_id` IS NOT NULL
         AND `message_id` IS NULL AND `diplomatic_action_id` IS NULL)
    );

CREATE TABLE `game_private_messages` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `sender_user_id` INT NOT NULL,
    `recipient_user_id` INT NOT NULL,
    `sender_country_id` INT NOT NULL,
    `recipient_country_id` INT NOT NULL,
    `sender_name` VARCHAR(50) NOT NULL,
    `recipient_name` VARCHAR(50) NOT NULL,
    `sender_country_name` VARCHAR(255) NOT NULL,
    `recipient_country_name` VARCHAR(255) NOT NULL,
    `sender_flag_path` VARCHAR(512) NOT NULL,
    `recipient_flag_path` VARCHAR(512) NOT NULL,
    `content` VARCHAR(3000) NOT NULL,
    `reply_to_id` INT NULL,
    `created_at` DATETIME NOT NULL,
    `read_at` DATETIME NULL,
    PRIMARY KEY (`id`),
    KEY `ix_pm_inbox` (`recipient_user_id`, `created_at`, `id`),
    KEY `ix_pm_sent` (`sender_user_id`, `created_at`, `id`),
    KEY `ix_pm_unread` (`recipient_user_id`, `read_at`),
    KEY `ix_pm_reply` (`reply_to_id`),
    CONSTRAINT `fk_pm_sender` FOREIGN KEY (`sender_user_id`)
        REFERENCES `game_users` (`id`) ON DELETE RESTRICT,
    CONSTRAINT `fk_pm_recipient` FOREIGN KEY (`recipient_user_id`)
        REFERENCES `game_users` (`id`) ON DELETE RESTRICT,
    CONSTRAINT `fk_pm_reply` FOREIGN KEY (`reply_to_id`)
        REFERENCES `game_private_messages` (`id`) ON DELETE RESTRICT,
    CONSTRAINT `ck_pm_content_length` CHECK (CHAR_LENGTH(`content`) BETWEEN 1 AND 3000),
    CONSTRAINT `ck_pm_different_users` CHECK (`sender_user_id` <> `recipient_user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
