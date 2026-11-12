-- UAT commerce, resource stocks, mines and mining budget. Existing budget totals remain unchanged.
CREATE TABLE game_resource_stocks (
	panstwo_id INTEGER NOT NULL, 
	resource VARCHAR(32) NOT NULL, 
	quantity NUMERIC(30, 0) NOT NULL, 
	PRIMARY KEY (panstwo_id, resource), 
	CONSTRAINT ck_resource_stock_quantity CHECK (quantity >= 0), 
	FOREIGN KEY(panstwo_id) REFERENCES panstwa (`PANSTWO_ID`)
)ENGINE=InnoDB;
CREATE TABLE game_mines (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	panstwo_id INTEGER NOT NULL, 
	region_id INTEGER NOT NULL, 
	resource VARCHAR(32) NOT NULL, 
	map_x DOUBLE NOT NULL, 
	map_y DOUBLE NOT NULL, 
	health INTEGER NOT NULL DEFAULT 100, 
	starts_at DATETIME NOT NULL, 
	ready_at DATETIME NOT NULL, 
	extracted_at DATETIME NOT NULL, 
	request_id VARCHAR(36) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_mine_request UNIQUE (panstwo_id, request_id), 
	CONSTRAINT ck_mine_values CHECK (health BETWEEN 0 AND 100 AND ready_at > starts_at AND extracted_at >= ready_at), 
	FOREIGN KEY(panstwo_id) REFERENCES panstwa (`PANSTWO_ID`), 
	FOREIGN KEY(region_id) REFERENCES regiony (region_id)
)ENGINE=InnoDB;
CREATE INDEX ix_game_mines_extracted_at ON game_mines (extracted_at);
CREATE INDEX ix_game_mines_panstwo_id ON game_mines (panstwo_id);
CREATE INDEX ix_game_mines_ready_at ON game_mines (ready_at);
CREATE INDEX ix_game_mines_region_id ON game_mines (region_id);
CREATE TABLE game_mining_expenses (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	panstwo_id INTEGER NOT NULL, 
	budget_id BIGINT NOT NULL, 
	mine_id INTEGER, 
	amount NUMERIC(30, 2) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_mining_expense_amount CHECK (amount > 0), 
	FOREIGN KEY(budget_id) REFERENCES game_state_budgets (id), 
	FOREIGN KEY(mine_id) REFERENCES game_mines (id) ON DELETE SET NULL
)ENGINE=InnoDB;
CREATE INDEX ix_game_mining_expenses_budget_id ON game_mining_expenses (budget_id);
CREATE TABLE game_port_tariffs (
	panstwo_id INTEGER NOT NULL, 
	rate NUMERIC(5, 2) NOT NULL, 
	PRIMARY KEY (panstwo_id), 
	CONSTRAINT ck_port_tariff_rate CHECK (rate BETWEEN 0 AND 100), 
	FOREIGN KEY(panstwo_id) REFERENCES panstwa (`PANSTWO_ID`)
)ENGINE=InnoDB;
CREATE TABLE game_trade_offers (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	panstwo_id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	cargo JSON NOT NULL, 
	price NUMERIC(30, 2) NOT NULL, 
	excluded JSON NOT NULL, 
	port_id INTEGER NOT NULL, 
	port_country_id INTEGER NOT NULL, 
	departure_rate NUMERIC(5, 2) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	request_id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_trade_offer_request UNIQUE (panstwo_id, request_id), 
	CONSTRAINT ck_trade_offer_values CHECK (price > 0 AND status IN ('open','sold','cancelled')), 
	FOREIGN KEY(panstwo_id) REFERENCES panstwa (`PANSTWO_ID`), 
	FOREIGN KEY(user_id) REFERENCES game_users (id), 
	FOREIGN KEY(port_id) REFERENCES miasta (miasto_id)
)ENGINE=InnoDB;
CREATE INDEX ix_game_trade_offers_panstwo_id ON game_trade_offers (panstwo_id);
CREATE INDEX ix_game_trade_offers_status ON game_trade_offers (status);
CREATE TABLE game_trade_shipments (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	offer_id INTEGER NOT NULL, 
	seller_id INTEGER NOT NULL, 
	buyer_id INTEGER NOT NULL, 
	cargo JSON NOT NULL, 
	departure_port_id INTEGER NOT NULL, 
	arrival_port_id INTEGER NOT NULL, 
	departure_fee NUMERIC(30, 2) NOT NULL, 
	arrival_fee NUMERIC(30, 2) NOT NULL, 
	source_x DOUBLE NOT NULL, 
	source_y DOUBLE NOT NULL, 
	target_x DOUBLE NOT NULL, 
	target_y DOUBLE NOT NULL, 
	distance_km DOUBLE NOT NULL, 
	starts_at DATETIME NOT NULL, 
	arrives_at DATETIME NOT NULL, 
	delivered_at DATETIME, 
	request_id VARCHAR(36) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_trade_shipment_request UNIQUE (buyer_id, request_id), 
	CONSTRAINT ck_trade_shipment_values CHECK (distance_km >= 0 AND departure_fee >= 0 AND arrival_fee >= 0 AND arrives_at > starts_at), 
	UNIQUE (offer_id), 
	FOREIGN KEY(offer_id) REFERENCES game_trade_offers (id), 
	FOREIGN KEY(buyer_id) REFERENCES panstwa (`PANSTWO_ID`), 
	FOREIGN KEY(departure_port_id) REFERENCES miasta (miasto_id), 
	FOREIGN KEY(arrival_port_id) REFERENCES miasta (miasto_id)
)ENGINE=InnoDB;
CREATE INDEX ix_game_trade_shipments_arrives_at ON game_trade_shipments (arrives_at);
CREATE INDEX ix_game_trade_shipments_buyer_id ON game_trade_shipments (buyer_id);
CREATE INDEX ix_game_trade_shipments_seller_id ON game_trade_shipments (seller_id);
CREATE TABLE game_trade_reserve_movements (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	panstwo_id INTEGER NOT NULL, 
	budget_id BIGINT, 
	shipment_id INTEGER NOT NULL, 
	amount NUMERIC(30, 2) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_trade_reserve_movement UNIQUE (shipment_id, panstwo_id), 
	CONSTRAINT ck_trade_reserve_amount CHECK (amount <> 0), 
	FOREIGN KEY(budget_id) REFERENCES game_state_budgets (id), 
	FOREIGN KEY(shipment_id) REFERENCES game_trade_shipments (id)
)ENGINE=InnoDB;
CREATE INDEX ix_game_trade_reserve_movements_budget_id ON game_trade_reserve_movements (budget_id);
CREATE INDEX ix_game_trade_reserve_movements_panstwo_id ON game_trade_reserve_movements (panstwo_id);
ALTER TABLE game_military_flights ADD COLUMN target_mine_id INTEGER NULL, ADD CONSTRAINT fk_military_flight_mine FOREIGN KEY (target_mine_id) REFERENCES game_mines (id) ON DELETE SET NULL;
ALTER TABLE game_intelligence_missions DROP CHECK ck_intelligence_mission_kind, ADD CONSTRAINT ck_intelligence_mission_kind_v2 CHECK (kind IN ('bases','defenses','nuclear','resources','infrastructure','silos','mines'));
ALTER TABLE game_budget_categories DROP CHECK ck_gbc_display_order, ADD CONSTRAINT ck_gbc_display_order_v2 CHECK (display_order BETWEEN 1 AND 18);
UPDATE game_budget_categories SET display_order=display_order+1 WHERE display_order>=7 ORDER BY display_order DESC;
INSERT INTO game_budget_categories (code,name_pl,display_order,is_reserve) VALUES ('mining_infrastructure','Infrastruktura wydobywcza',7,0);
INSERT INTO game_state_budget_allocations (budget_id,category_code,share_percent,amount) SELECT b.id,'mining_infrastructure',0,0 FROM game_state_budgets b WHERE NOT EXISTS (SELECT 1 FROM game_state_budget_allocations a WHERE a.budget_id=b.id AND a.category_code='mining_infrastructure');
