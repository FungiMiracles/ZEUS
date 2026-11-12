-- Do przeglądu i ręcznego uruchomienia. Ten plik nie jest wykonywany przez aplikację.
-- Wymagane istniejące tabele game_users i panstwa z kluczami INT oraz InnoDB.
-- Daty rzeczywiste zapisywane są w UTC; interfejs przelicza je na Europe/Warsaw.
USE `entenda_uat_db`;

CREATE TABLE `game_forum_messages` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `user_id` INT NOT NULL,
    `panstwo_id` INT NOT NULL,
    `author_name` VARCHAR(50) NOT NULL,
    `country_name` VARCHAR(255) NOT NULL,
    `flag_path` VARCHAR(512) NOT NULL,
    `content` VARCHAR(1000) NOT NULL,
    `entenda_date` DATE NOT NULL,
    `created_at` DATETIME NOT NULL,
    `edited_at` DATETIME NULL,
    `edited_entenda_date` DATE NULL,
    `version` INT NOT NULL DEFAULT 1,
    PRIMARY KEY (`id`),
    KEY `ix_forum_created_id` (`created_at`, `id`),
    KEY `ix_forum_user` (`user_id`),
    KEY `ix_forum_country` (`panstwo_id`),
    CONSTRAINT `fk_forum_user` FOREIGN KEY (`user_id`)
        REFERENCES `game_users` (`id`) ON DELETE RESTRICT,
    CONSTRAINT `fk_forum_country` FOREIGN KEY (`panstwo_id`)
        REFERENCES `panstwa` (`PANSTWO_ID`) ON DELETE RESTRICT,
    CONSTRAINT `ck_forum_content_length` CHECK (CHAR_LENGTH(`content`) BETWEEN 1 AND 1000)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
