-- UAT: intelligence and safe removal of destroyed military bases.
ALTER TABLE game_military_expenses DROP FOREIGN KEY `game_military_expenses_ibfk_1`, MODIFY COLUMN base_id INTEGER NULL, ADD CONSTRAINT `fk_detach_game_military_expenses_base_id` FOREIGN KEY (base_id) REFERENCES game_military_bases (id) ON DELETE SET NULL;
ALTER TABLE game_military_flights DROP FOREIGN KEY `game_military_flights_ibfk_2`, MODIFY COLUMN source_base_id INTEGER NULL, ADD CONSTRAINT `fk_detach_game_military_flights_source_base_id` FOREIGN KEY (source_base_id) REFERENCES game_military_bases (id) ON DELETE SET NULL;
ALTER TABLE game_military_flights DROP FOREIGN KEY `fk_flight_target_base`, MODIFY COLUMN target_base_id INTEGER NULL, ADD CONSTRAINT `fk_detach_game_military_flights_target_base_id` FOREIGN KEY (target_base_id) REFERENCES game_military_bases (id) ON DELETE SET NULL;
ALTER TABLE game_military_vessels DROP FOREIGN KEY `game_military_vessels_ibfk_2`, MODIFY COLUMN base_id INTEGER NULL, ADD CONSTRAINT `fk_detach_game_military_vessels_base_id` FOREIGN KEY (base_id) REFERENCES game_military_bases (id) ON DELETE SET NULL;
ALTER TABLE game_military_vessels DROP FOREIGN KEY `game_military_vessels_ibfk_3`, MODIFY COLUMN return_base_id INTEGER NULL, ADD CONSTRAINT `fk_detach_game_military_vessels_return_base_id` FOREIGN KEY (return_base_id) REFERENCES game_military_bases (id) ON DELETE SET NULL;
ALTER TABLE game_missile_defense_expenses DROP FOREIGN KEY `game_missile_defense_expenses_ibfk_1`, MODIFY COLUMN defense_id INTEGER NULL, ADD CONSTRAINT `fk_detach_game_missile_defense_expenses_defense_id` FOREIGN KEY (defense_id) REFERENCES game_missile_defenses (id) ON DELETE SET NULL;
ALTER TABLE game_military_flights ADD COLUMN target_kind VARCHAR(16) NOT NULL DEFAULT 'region';
ALTER TABLE game_military_vessels ADD COLUMN region_id INTEGER NULL;
UPDATE game_military_flights SET target_kind=CASE WHEN target_base_id IS NOT NULL THEN 'base' WHEN target_vessel_id IS NOT NULL THEN 'vessel' WHEN city_id IS NOT NULL THEN 'city' ELSE target_kind END;
UPDATE game_military_vessels v JOIN game_military_bases b ON b.id=v.base_id SET v.region_id=b.region_id WHERE v.region_id IS NULL;
CREATE TABLE game_intelligence_agents (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	panstwo_id INTEGER NOT NULL, 
	level INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_intelligence_agent_level CHECK (level BETWEEN 1 AND 7), 
	FOREIGN KEY(panstwo_id) REFERENCES panstwa (`PANSTWO_ID`)
)ENGINE=InnoDB;
CREATE INDEX ix_game_intelligence_agents_panstwo_id ON game_intelligence_agents (panstwo_id);
CREATE TABLE game_counterintelligence (
	panstwo_id INTEGER NOT NULL, 
	level INTEGER NOT NULL, 
	PRIMARY KEY (panstwo_id), 
	CONSTRAINT ck_counterintelligence_level CHECK (level BETWEEN 1 AND 7), 
	FOREIGN KEY(panstwo_id) REFERENCES panstwa (`PANSTWO_ID`)
)ENGINE=InnoDB;
CREATE TABLE game_intelligence_missions (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	panstwo_id INTEGER NOT NULL, 
	agent_id INTEGER NOT NULL, 
	region_id INTEGER NOT NULL, 
	target_country_id INTEGER NOT NULL, 
	region_name VARCHAR(255) NOT NULL, 
	kind VARCHAR(24) NOT NULL, 
	starts_at DATETIME NOT NULL, 
	ends_at DATETIME NOT NULL, 
	completed_at DATETIME, 
	success BOOL, 
	effective_chance INTEGER, 
	report JSON, 
	notification_id INTEGER, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_intelligence_mission_time CHECK (ends_at > starts_at), 
	CONSTRAINT ck_intelligence_mission_kind CHECK (kind IN ('bases','defenses','nuclear','resources','infrastructure','silos')), 
	FOREIGN KEY(panstwo_id) REFERENCES panstwa (`PANSTWO_ID`), 
	FOREIGN KEY(agent_id) REFERENCES game_intelligence_agents (id), 
	FOREIGN KEY(region_id) REFERENCES regiony (region_id), 
	UNIQUE (notification_id), 
	FOREIGN KEY(notification_id) REFERENCES game_notifications (id)
)ENGINE=InnoDB;
CREATE INDEX ix_game_intelligence_missions_ends_at ON game_intelligence_missions (ends_at);
CREATE INDEX ix_game_intelligence_missions_panstwo_id ON game_intelligence_missions (panstwo_id);
CREATE INDEX ix_intelligence_mission_due ON game_intelligence_missions (completed_at, ends_at);
CREATE TABLE game_intelligence_expenses (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	panstwo_id INTEGER NOT NULL, 
	budget_id BIGINT NOT NULL, 
	amount NUMERIC(30, 2) NOT NULL, 
	request_id VARCHAR(36) NOT NULL, 
	payload JSON NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_intelligence_expense_request UNIQUE (panstwo_id, request_id), 
	CONSTRAINT ck_intelligence_expense_amount CHECK (amount > 0), 
	FOREIGN KEY(budget_id) REFERENCES game_state_budgets (id)
)ENGINE=InnoDB;
CREATE INDEX ix_game_intelligence_expenses_budget_id ON game_intelligence_expenses (budget_id);
CREATE INDEX ix_game_intelligence_expenses_panstwo_id ON game_intelligence_expenses (panstwo_id);
