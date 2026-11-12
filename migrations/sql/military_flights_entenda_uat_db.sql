USE entenda_uat_db;
ALTER TABLE game_military_bases
 ADD COLUMN map_x DOUBLE NULL,
 ADD COLUMN map_y DOUBLE NULL,
 ADD COLUMN health INT NOT NULL DEFAULT 100,
 ADD CONSTRAINT ck_military_base_health CHECK (health BETWEEN 0 AND 100),
 ADD CONSTRAINT ck_military_base_position CHECK ((map_x IS NULL AND map_y IS NULL) OR (map_x IS NOT NULL AND map_y IS NOT NULL));
CREATE TABLE game_map_calibration (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	reference_city_a INTEGER NOT NULL, 
	reference_city_b INTEGER NOT NULL, 
	reference_km DOUBLE NOT NULL, 
	km_per_unit DOUBLE NOT NULL, 
	reference_a_x DOUBLE NOT NULL, 
	reference_a_y DOUBLE NOT NULL, 
	reference_b_x DOUBLE NOT NULL, 
	reference_b_y DOUBLE NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (reference_km > 0 AND km_per_unit > 0)
)ENGINE=InnoDB;
CREATE TABLE game_military_flights (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	order_id INTEGER NOT NULL, 
	panstwo_id INTEGER NOT NULL, 
	target_country_id INTEGER NOT NULL, 
	source_base_id INTEGER NOT NULL, 
	city_id INTEGER, 
	target_name VARCHAR(255) NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	missile_type VARCHAR(16) NOT NULL, 
	missiles INTEGER NOT NULL, 
	source_x DOUBLE NOT NULL, 
	source_y DOUBLE NOT NULL, 
	target_x DOUBLE NOT NULL, 
	target_y DOUBLE NOT NULL, 
	distance_km DOUBLE NOT NULL, 
	starts_at DATETIME NOT NULL, 
	impact_at DATETIME NOT NULL, 
	fighter_arrives_at DATETIME, 
	returns_at DATETIME, 
	impacted_at DATETIME, 
	returned_at DATETIME, 
	casualties INTEGER, 
	PRIMARY KEY (id), 
	CHECK (missiles > 0 AND distance_km >= 0), 
	CHECK (casualties IS NULL OR casualties >= 0), 
	UNIQUE (order_id), 
	FOREIGN KEY(order_id) REFERENCES game_military_orders (id), 
	FOREIGN KEY(source_base_id) REFERENCES game_military_bases (id), 
	FOREIGN KEY(city_id) REFERENCES miasta (miasto_id)
)ENGINE=InnoDB;
CREATE INDEX ix_flight_impact_due ON game_military_flights (impacted_at, impact_at);
CREATE INDEX ix_flight_return_due ON game_military_flights (returned_at, returns_at);
CREATE INDEX ix_game_military_flights_impact_at ON game_military_flights (impact_at);
CREATE INDEX ix_game_military_flights_panstwo_id ON game_military_flights (panstwo_id);
CREATE INDEX ix_game_military_flights_target_country_id ON game_military_flights (target_country_id);
INSERT INTO game_map_calibration (id,reference_city_a,reference_city_b,reference_km,km_per_unit,reference_a_x,reference_a_y,reference_b_x,reference_b_y) VALUES (1,1,852,100,3.910919870403471,954.7510623012616,-1801.62366708549,952.4987942837062,-1776.1536230000308);
