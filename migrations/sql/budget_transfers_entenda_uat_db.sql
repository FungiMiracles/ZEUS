CREATE TABLE game_budget_transfers (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	budget_id BIGINT NOT NULL, 
	user_id INTEGER NOT NULL, 
	source VARCHAR(48) NOT NULL, 
	destination VARCHAR(48) NOT NULL, 
	amount NUMERIC(30, 2) NOT NULL, 
	request_id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	game_datetime DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_budget_transfer_request UNIQUE (user_id, request_id), 
	CONSTRAINT ck_budget_transfer_amount CHECK (amount > 0 AND source <> destination), 
	FOREIGN KEY(budget_id) REFERENCES game_state_budgets (id), 
	FOREIGN KEY(user_id) REFERENCES game_users (id)
)ENGINE=InnoDB;
CREATE INDEX ix_game_budget_transfers_budget_id ON game_budget_transfers (budget_id);
