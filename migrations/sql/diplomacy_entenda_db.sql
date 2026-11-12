-- Etap 3: dyplomacja. Wykonać jednokrotnie po wcześniejszych skryptach forum i powiadomień.
-- Do ręcznego przeglądu i uruchomienia. Nie zmienia istniejących stosunków ani audytu.
USE `entenda_db`;

CREATE TABLE `game_diplomatic_actions` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `sender_user_id` INT NOT NULL,
    `recipient_user_id` INT NOT NULL,
    `source_country_id` INT NOT NULL,
    `target_country_id` INT NOT NULL,
    `source_country_name` VARCHAR(255) NOT NULL,
    `target_country_name` VARCHAR(255) NOT NULL,
    `kind` VARCHAR(32) NOT NULL,
    `status` VARCHAR(16) NOT NULL,
    `proposed_relation_id` INT NULL,
    `expected_relation_id` INT NOT NULL,
    `expected_state_id` INT NOT NULL,
    `expected_audit_id` INT NOT NULL,
    `created_at` DATETIME NOT NULL,
    `decided_at` DATETIME NULL,
    PRIMARY KEY (`id`),
    KEY `ix_diplomatic_pair_status` (`source_country_id`, `target_country_id`, `status`),
    KEY `ix_diplomatic_recipient` (`recipient_user_id`, `status`),
    KEY `ix_diplomatic_sender` (`sender_user_id`),
    KEY `ix_diplomatic_target` (`target_country_id`),
    KEY `ix_diplomatic_relation` (`proposed_relation_id`),
    CONSTRAINT `fk_diplomatic_sender` FOREIGN KEY (`sender_user_id`)
        REFERENCES `game_users` (`id`) ON DELETE RESTRICT,
    CONSTRAINT `fk_diplomatic_recipient` FOREIGN KEY (`recipient_user_id`)
        REFERENCES `game_users` (`id`) ON DELETE RESTRICT,
    CONSTRAINT `fk_diplomatic_source` FOREIGN KEY (`source_country_id`)
        REFERENCES `panstwa` (`PANSTWO_ID`) ON DELETE RESTRICT,
    CONSTRAINT `fk_diplomatic_target` FOREIGN KEY (`target_country_id`)
        REFERENCES `panstwa` (`PANSTWO_ID`) ON DELETE RESTRICT,
    CONSTRAINT `fk_diplomatic_relation` FOREIGN KEY (`proposed_relation_id`)
        REFERENCES `dict_stosunki_relacja` (`relacja_id`) ON DELETE RESTRICT,
    CONSTRAINT `ck_diplomatic_kind`
        CHECK (`kind` IN ('WAR', 'PEACE', 'CEASEFIRE', 'RELATION')),
    CONSTRAINT `ck_diplomatic_status`
        CHECK (`status` IN ('PENDING', 'APPLIED', 'ACCEPTED', 'REJECTED', 'EXPIRED')),
    CONSTRAINT `ck_diplomatic_different_parties`
        CHECK (`source_country_id` <> `target_country_id`
               AND `sender_user_id` <> `recipient_user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

ALTER TABLE `game_notifications`
    MODIFY COLUMN `message_id` INT NULL,
    ADD COLUMN `diplomatic_action_id` INT NULL,
    ADD UNIQUE KEY `uq_notification_user_diplomacy` (`user_id`, `diplomatic_action_id`),
    ADD KEY `ix_notification_diplomacy` (`diplomatic_action_id`),
    ADD CONSTRAINT `fk_notification_diplomacy` FOREIGN KEY (`diplomatic_action_id`)
        REFERENCES `game_diplomatic_actions` (`id`) ON DELETE RESTRICT,
    ADD CONSTRAINT `ck_notification_target` CHECK (
        (`notification_type` = 'FORUM_MESSAGE' AND `message_id` IS NOT NULL
         AND `diplomatic_action_id` IS NULL)
        OR
        (`notification_type` = 'DIPLOMACY' AND `diplomatic_action_id` IS NOT NULL
         AND `message_id` IS NULL)
    );
