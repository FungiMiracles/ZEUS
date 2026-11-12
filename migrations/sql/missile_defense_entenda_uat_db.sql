-- UAT: coastal naval placement, named vessels, combat targets and missile defense.
ALTER TABLE game_military_vessels ADD COLUMN name VARCHAR(120) NULL, ADD COLUMN health INTEGER NOT NULL DEFAULT 100;
ALTER TABLE game_military_vessels DROP CHECK ck_vessel_status;
ALTER TABLE game_military_vessels ADD CONSTRAINT ck_vessel_status CHECK (status IN ('sailing','stationed','returning','docked','sunk')), ADD CONSTRAINT ck_vessel_health CHECK (health BETWEEN 0 AND 100);
ALTER TABLE game_military_flights ADD COLUMN target_base_id INTEGER NULL, ADD COLUMN target_vessel_id INTEGER NULL, ADD COLUMN intercepted INTEGER NOT NULL DEFAULT 0, ADD COLUMN damage JSON NULL, ADD CONSTRAINT fk_flight_target_base FOREIGN KEY (target_base_id) REFERENCES game_military_bases(id), ADD CONSTRAINT fk_flight_target_vessel FOREIGN KEY (target_vessel_id) REFERENCES game_military_vessels(id);
CREATE TABLE game_missile_defenses (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	panstwo_id INTEGER NOT NULL, 
	region_id INTEGER NOT NULL, 
	target_kind VARCHAR(16) NOT NULL, 
	target_id INTEGER NOT NULL, 
	level INTEGER NOT NULL, 
	ammunition INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_missile_defense_target UNIQUE (target_kind, target_id), 
	CONSTRAINT ck_missile_defense_kind CHECK (target_kind IN ('region','city','base')), 
	CONSTRAINT ck_missile_defense_values CHECK (level BETWEEN 1 AND 7 AND ammunition BETWEEN 0 AND 10000), 
	FOREIGN KEY(panstwo_id) REFERENCES panstwa (`PANSTWO_ID`), 
	FOREIGN KEY(region_id) REFERENCES regiony (region_id)
)ENGINE=InnoDB;
CREATE INDEX ix_game_missile_defenses_panstwo_id ON game_missile_defenses (panstwo_id);
CREATE INDEX ix_game_missile_defenses_region_id ON game_missile_defenses (region_id);
CREATE TABLE game_missile_defense_expenses (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	panstwo_id INTEGER NOT NULL, 
	budget_id BIGINT NOT NULL, 
	defense_id INTEGER NOT NULL, 
	amount NUMERIC(30, 2) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_missile_defense_expense CHECK (amount >= 0), 
	FOREIGN KEY(defense_id) REFERENCES game_missile_defenses (id)
)ENGINE=InnoDB;
CREATE INDEX ix_game_missile_defense_expenses_budget_id ON game_missile_defense_expenses (budget_id);
CREATE INDEX ix_game_missile_defense_expenses_panstwo_id ON game_missile_defense_expenses (panstwo_id);
