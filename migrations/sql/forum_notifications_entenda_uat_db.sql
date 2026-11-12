-- Uruchomić jednokrotnie po wcześniejszych skryptach forum i forum_replies.
-- Nie wykonuje się automatycznie. Nie tworzy powiadomień o starych wpisach.
USE `entenda_uat_db`;

CREATE TABLE `game_forum_message_recipients` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `message_id` INT NOT NULL,
    `user_id` INT NOT NULL,
    `name` VARCHAR(50) NOT NULL,
    `country_name` VARCHAR(255) NOT NULL,
    `flag_path` VARCHAR(512) NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_forum_message_recipient` (`message_id`, `user_id`),
    KEY `ix_forum_recipient_user` (`user_id`),
    CONSTRAINT `fk_forum_mr_message` FOREIGN KEY (`message_id`)
        REFERENCES `game_forum_messages` (`id`) ON DELETE RESTRICT,
    CONSTRAINT `fk_forum_mr_user` FOREIGN KEY (`user_id`)
        REFERENCES `game_users` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `game_notifications` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `user_id` INT NOT NULL,
    `message_id` INT NOT NULL,
    `notification_type` VARCHAR(32) NOT NULL DEFAULT 'FORUM_MESSAGE',
    `created_at` DATETIME NOT NULL,
    `read_at` DATETIME NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_notification_user_message` (`user_id`, `message_id`),
    KEY `ix_notification_user_created` (`user_id`, `created_at`, `id`),
    KEY `ix_notification_user_unread` (`user_id`, `read_at`),
    KEY `ix_notification_message` (`message_id`),
    CONSTRAINT `fk_notification_user` FOREIGN KEY (`user_id`)
        REFERENCES `game_users` (`id`) ON DELETE RESTRICT,
    CONSTRAINT `fk_notification_message` FOREIGN KEY (`message_id`)
        REFERENCES `game_forum_messages` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Przeniesienie dotychczasowych pojedynczych adresatów.
-- Dotychczasowe kolumny pozostają, aby zachować zgodność.
INSERT INTO `game_forum_message_recipients`
    (`message_id`, `user_id`, `name`, `country_name`, `flag_path`)
SELECT m.`id`, m.`recipient_user_id`, COALESCE(m.`recipient_name`, ''),
       COALESCE(m.`recipient_country_name`, ''), COALESCE(m.`recipient_flag_path`, '')
FROM `game_forum_messages` AS m
WHERE m.`recipient_user_id` IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM `game_forum_message_recipients` AS r
      WHERE r.`message_id` = m.`id` AND r.`user_id` = m.`recipient_user_id`
  );
