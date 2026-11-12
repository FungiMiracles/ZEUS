-- Wykonać przed uruchomieniem nowej wersji aplikacji UAT.
USE entenda_uat_db;
CREATE TABLE game_infrastructure_projects (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	panstwo_id INTEGER NOT NULL, 
	region_id INTEGER NOT NULL, 
	budget_id BIGINT NOT NULL, 
	metric VARCHAR(24) NOT NULL, 
	levels INTEGER NOT NULL, 
	cost NUMERIC(30, 2) NOT NULL, 
	budget_spent NUMERIC(30, 2) NOT NULL, 
	reserve_spent NUMERIC(30, 2) NOT NULL, 
	starts_at DATETIME NOT NULL, 
	ends_at DATETIME NOT NULL, 
	completed_at DATETIME, 
	PRIMARY KEY (id), 
	CHECK (levels > 0 AND levels <= 100), 
	CHECK (metric IN ('road', 'rail', 'energy', 'housing', 'port')), 
	CHECK (ends_at > starts_at), 
	CHECK (cost >= 0 AND budget_spent >= 0 AND reserve_spent >= 0 AND cost = budget_spent + reserve_spent)
)ENGINE=InnoDB;
CREATE INDEX ix_game_infrastructure_projects_budget_id ON game_infrastructure_projects (budget_id);
CREATE INDEX ix_game_infrastructure_projects_panstwo_id ON game_infrastructure_projects (panstwo_id);
CREATE INDEX ix_game_infrastructure_projects_region_id ON game_infrastructure_projects (region_id);
