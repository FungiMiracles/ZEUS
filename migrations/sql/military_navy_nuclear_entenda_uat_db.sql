-- UAT: names, nuclear silos, persistent navy and nuclear flights.
ALTER TABLE game_military_bases ADD COLUMN name VARCHAR(120) NULL, ADD COLUMN operational BOOLEAN NOT NULL DEFAULT 1;
ALTER TABLE game_military_bases DROP CHECK game_military_bases_chk_1;
ALTER TABLE game_military_bases ADD CONSTRAINT ck_military_base_kind CHECK (kind IN ('land','air','naval','nuclear'));
CREATE TABLE game_military_vessels (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	panstwo_id INTEGER NOT NULL, 
	base_id INTEGER NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	source_x DOUBLE NOT NULL, 
	source_y DOUBLE NOT NULL, 
	target_x DOUBLE NOT NULL, 
	target_y DOUBLE NOT NULL, 
	starts_at DATETIME NOT NULL, 
	arrives_at DATETIME NOT NULL, 
	return_base_id INTEGER, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_vessel_kind CHECK (kind IN ('warships','submarines')), 
	CONSTRAINT ck_vessel_status CHECK (status IN ('sailing','stationed','returning','docked')), 
	FOREIGN KEY(panstwo_id) REFERENCES panstwa (`PANSTWO_ID`), 
	FOREIGN KEY(base_id) REFERENCES game_military_bases (id), 
	FOREIGN KEY(return_base_id) REFERENCES game_military_bases (id)
)ENGINE=InnoDB;
CREATE INDEX ix_military_vessel_country ON game_military_vessels (panstwo_id);
CREATE INDEX ix_military_vessel_base ON game_military_vessels (base_id);
CREATE INDEX ix_military_vessel_arrival ON game_military_vessels (arrives_at);
ALTER TABLE game_military_flights ADD COLUMN source_vessel_id INTEGER NULL, ADD COLUMN is_nuclear BOOLEAN NOT NULL DEFAULT 0, ADD CONSTRAINT fk_military_flight_vessel FOREIGN KEY (source_vessel_id) REFERENCES game_military_vessels(id);
