
CREATE TABLE wiki_region_secessions (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	region_id INTEGER NOT NULL, 
	source_country_id INTEGER NOT NULL, 
	new_country_id INTEGER NOT NULL, 
	capital_city_id INTEGER, 
	original_capital_type INTEGER, 
	flag_snapshot BLOB(16777215), 
	map_snapshot BLOB(16777215), 
	map_mime VARCHAR(50), 
	original_overseas BOOL NOT NULL, 
	created_at DATETIME NOT NULL, 
	actor VARCHAR(120) NOT NULL, 
	request_id VARCHAR(36) NOT NULL, 
	rejoined_country_id INTEGER, 
	rejoined_at DATETIME, 
	rejoined_by VARCHAR(120), 
	rejoin_request_id VARCHAR(36), 
	PRIMARY KEY (id), 
	FOREIGN KEY(region_id) REFERENCES regiony (region_id), 
	FOREIGN KEY(source_country_id) REFERENCES panstwa (`PANSTWO_ID`), 
	UNIQUE (new_country_id), 
	FOREIGN KEY(new_country_id) REFERENCES panstwa (`PANSTWO_ID`), 
	FOREIGN KEY(capital_city_id) REFERENCES miasta (miasto_id), 
	UNIQUE (request_id), 
	FOREIGN KEY(rejoined_country_id) REFERENCES panstwa (`PANSTWO_ID`), 
	UNIQUE (rejoin_request_id)
)

;
