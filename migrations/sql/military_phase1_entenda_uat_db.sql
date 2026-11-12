USE entenda_uat_db;
CREATE TABLE game_military_bases (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	panstwo_id INTEGER NOT NULL, 
	region_id INTEGER NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	level INTEGER NOT NULL, 
	garrison JSON NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (kind IN ('land','air','naval')), 
	CHECK (level BETWEEN 1 AND 7), 
	FOREIGN KEY(panstwo_id) REFERENCES panstwa (`PANSTWO_ID`), 
	FOREIGN KEY(region_id) REFERENCES regiony (region_id)
)ENGINE=InnoDB;
CREATE INDEX ix_game_military_bases_panstwo_id ON game_military_bases (panstwo_id);
CREATE INDEX ix_game_military_bases_region_id ON game_military_bases (region_id);
CREATE TABLE game_military_expenses (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	panstwo_id INTEGER NOT NULL, 
	budget_id BIGINT NOT NULL, 
	base_id INTEGER NOT NULL, 
	level INTEGER NOT NULL, 
	amount NUMERIC(30, 2) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_military_base_upgrade UNIQUE (base_id, level), 
	CHECK (amount >= 0), 
	FOREIGN KEY(base_id) REFERENCES game_military_bases (id)
)ENGINE=InnoDB;
CREATE INDEX ix_game_military_expenses_budget_id ON game_military_expenses (budget_id);
CREATE INDEX ix_game_military_expenses_panstwo_id ON game_military_expenses (panstwo_id);
CREATE TABLE game_military_maintenance (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	panstwo_id INTEGER NOT NULL, 
	game_year INTEGER NOT NULL, 
	period INTEGER NOT NULL, 
	budget_id BIGINT, 
	amount NUMERIC(30, 2) NOT NULL, 
	assessed_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_military_maintenance_period UNIQUE (panstwo_id, game_year, period), 
	CHECK (amount >= 0)
)ENGINE=InnoDB;
CREATE INDEX ix_game_military_maintenance_budget_id ON game_military_maintenance (budget_id);
CREATE INDEX ix_game_military_maintenance_panstwo_id ON game_military_maintenance (panstwo_id);
CREATE TABLE game_military_orders (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	panstwo_id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	region_id INTEGER NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	payload JSON NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (kind IN ('air','missile','naval','land'))
)ENGINE=InnoDB;
CREATE INDEX ix_game_military_orders_panstwo_id ON game_military_orders (panstwo_id);
ALTER TABLE wojsko
 ADD COLUMN rakiety_krotkiego_zasiegu BIGINT NOT NULL DEFAULT 0,
 ADD COLUMN rakiety_sredniego_zasiegu BIGINT NOT NULL DEFAULT 0,
 ADD COLUMN rakiety_dalekiego_zasiegu BIGINT NOT NULL DEFAULT 0;
ALTER TABLE game_notifications DROP CHECK ck_notification_target, ADD COLUMN system_text VARCHAR(1000) NULL, ADD CONSTRAINT ck_notification_target CHECK (((notification_type = 'FORUM_MESSAGE' AND message_id IS NOT NULL AND diplomatic_action_id IS NULL AND generated_event_id IS NULL AND infrastructure_project_id IS NULL AND infrastructure_text IS NULL) OR (notification_type = 'DIPLOMACY' AND diplomatic_action_id IS NOT NULL AND message_id IS NULL AND generated_event_id IS NULL AND infrastructure_project_id IS NULL AND infrastructure_text IS NULL) OR (notification_type = 'GENERATED_EVENT' AND generated_event_id IS NOT NULL AND message_id IS NULL AND diplomatic_action_id IS NULL AND infrastructure_project_id IS NULL AND infrastructure_text IS NULL) OR (notification_type = 'INFRASTRUCTURE_COMPLETED' AND infrastructure_project_id IS NOT NULL AND infrastructure_text IS NOT NULL AND message_id IS NULL AND diplomatic_action_id IS NULL AND generated_event_id IS NULL)) AND system_text IS NULL OR (notification_type = 'SYSTEM' AND system_text IS NOT NULL AND message_id IS NULL AND diplomatic_action_id IS NULL AND generated_event_id IS NULL AND infrastructure_project_id IS NULL AND infrastructure_text IS NULL));
