-- Panel surowców WIKI. Wykonać jednokrotnie po przeglądzie.
-- Wymagane istniejące tabele panstwa, regiony, dict_zasoby i regiony_zasoby.
-- Nie usuwa duplikatów, nie zmienia istniejących kodów, cen ani ilości złóż.
USE `entenda_db`;

DELIMITER $$
CREATE PROCEDURE `zeus_prepare_natural_resources`()
BEGIN
    -- Kontrole poprzedzają zmiany trwałych tabel.
    IF EXISTS (
        SELECT 1 FROM `regiony_zasoby`
        GROUP BY `region_id`, `zasob_id` HAVING COUNT(*) > 1
    ) THEN
        SELECT `region_id`, `zasob_id`, COUNT(*) AS `liczba_wpisow`
        FROM `regiony_zasoby`
        GROUP BY `region_id`, `zasob_id` HAVING COUNT(*) > 1;
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Duplikaty regiony_zasoby: wymagany reczny przeglad. Niczego nie usunieto.';
    END IF;

    DROP TEMPORARY TABLE IF EXISTS `zeus_natural_resource_seed`;
    CREATE TEMPORARY TABLE `zeus_natural_resource_seed` (
        `code` VARCHAR(50) NOT NULL PRIMARY KEY,
        `name` VARCHAR(255) NOT NULL
    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

    INSERT INTO `zeus_natural_resource_seed` (`code`, `name`) VALUES
        ('wegiel_kamienny', 'Węgiel kamienny'),
        ('ropa_naftowa', 'Ropa naftowa'),
        ('zloto', 'Złoto'),
        ('srebro', 'Srebro'),
        ('kamien', 'Kamień'),
        ('natsyt', 'Natsyt'),
        ('kerbit', 'Kerbit'),
        ('cemium', 'Cemium');

    IF EXISTS (
        SELECT s.`code`
        FROM `zeus_natural_resource_seed` AS s
        JOIN `dict_zasoby` AS d ON
            LOWER(REPLACE(REPLACE(CONVERT(d.`zasob_kod` USING utf8mb4), '_', ''), ' ', '')) COLLATE utf8mb4_unicode_ci
                = REPLACE(s.`code`, '_', '')
            OR CONVERT(d.`zasob_nazwa` USING utf8mb4) COLLATE utf8mb4_unicode_ci = s.`name`
        GROUP BY s.`code` HAVING COUNT(*) > 1
    ) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Kilka pozycji slownika odpowiada jednemu surowcowi. Wymagany reczny przeglad.';
    END IF;

    IF EXISTS (
        SELECT d.`zasob_id`
        FROM `dict_zasoby` AS d
        JOIN `zeus_natural_resource_seed` AS s ON
            LOWER(REPLACE(REPLACE(CONVERT(d.`zasob_kod` USING utf8mb4), '_', ''), ' ', '')) COLLATE utf8mb4_unicode_ci
                = REPLACE(s.`code`, '_', '')
            OR CONVERT(d.`zasob_nazwa` USING utf8mb4) COLLATE utf8mb4_unicode_ci = s.`name`
        GROUP BY d.`zasob_id` HAVING COUNT(*) > 1
    ) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Jedna pozycja slownika odpowiada kilku surowcom. Wymagany reczny przeglad.';
    END IF;

    CREATE TABLE `country_mining_settings` (
        `panstwo_id` INT NOT NULL,
        `technology` SMALLINT NOT NULL DEFAULT 0,
        `version` INT NOT NULL DEFAULT 1,
        PRIMARY KEY (`panstwo_id`),
        CONSTRAINT `fk_mining_country` FOREIGN KEY (`panstwo_id`)
            REFERENCES `panstwa` (`PANSTWO_ID`) ON DELETE CASCADE,
        CONSTRAINT `ck_mining_technology` CHECK (`technology` BETWEEN 0 AND 100)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

    ALTER TABLE `regiony_zasoby`
        ADD CONSTRAINT `uq_region_resource` UNIQUE (`region_id`, `zasob_id`);

    -- Dodajemy tylko brakujące surowce. Istniejące identyfikatory i kody pozostają.
    INSERT INTO `dict_zasoby`
        (`zasob_kod`, `zasob_nazwa`, `zasob_kategoria`, `zasob_jednostka`,
         `cena_bazowa`, `czy_strategiczny`, `czy_wydobywalny`)
    SELECT s.`code`, s.`name`, 'Surowce naturalne', 'jednostka', 0, 'NIE', 'TAK'
    FROM `zeus_natural_resource_seed` AS s
    WHERE NOT EXISTS (
        SELECT 1 FROM `dict_zasoby` AS d
        WHERE LOWER(REPLACE(REPLACE(CONVERT(d.`zasob_kod` USING utf8mb4), '_', ''), ' ', '')) COLLATE utf8mb4_unicode_ci
                = REPLACE(s.`code`, '_', '')
           OR CONVERT(d.`zasob_nazwa` USING utf8mb4) COLLATE utf8mb4_unicode_ci = s.`name`
    );

    DROP TEMPORARY TABLE `zeus_natural_resource_seed`;
END$$

CALL `zeus_prepare_natural_resources`()$$
DROP PROCEDURE `zeus_prepare_natural_resources`$$
DELIMITER ;
