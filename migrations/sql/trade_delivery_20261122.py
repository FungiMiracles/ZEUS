"""Drogi dostawy w handlu (UAT / PREPROD, 22 Nov 2026).

    venv/bin/python migrations/sql/trade_delivery_20261122.py uat
    venv/bin/python migrations/sql/trade_delivery_20261122.py preprod

Dodaje kolumnę game_trade_shipments.legs (odcinki podróży: kolej / statek / samolot) oraz tabele game_land_customs
(cło lądowe państw) i game_imf_shipping_fees (opłaty za wysyłkę na koncie MFW). Skrypt jest idempotentny.
"""
import sys
from pathlib import Path
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
sys.path.insert(0, str(Path(__file__).resolve().parent))
from production_orders_20261122 import TARGETS, database_url

TABLES = {
    'game_land_customs': """CREATE TABLE game_land_customs (
  panstwo_id INT NOT NULL PRIMARY KEY,
  rate DECIMAL(5,2) NOT NULL DEFAULT 0,
  updated_at DATETIME NOT NULL,
  CONSTRAINT fk_game_land_customs_country FOREIGN KEY (panstwo_id) REFERENCES panstwa (PANSTWO_ID),
  CONSTRAINT ck_land_customs_rate CHECK (rate BETWEEN 0 AND 100)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    'game_imf_shipping_fees': """CREATE TABLE game_imf_shipping_fees (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  shipment_id INT NOT NULL,
  buyer_id INT NOT NULL,
  seller_id INT NOT NULL,
  transport VARCHAR(8) NOT NULL,
  rate DECIMAL(5,2) NOT NULL,
  amount DECIMAL(30,2) NOT NULL,
  created_at DATETIME NOT NULL,
  UNIQUE KEY uq_imf_shipping_fee_shipment (shipment_id),
  KEY ix_game_imf_shipping_fees_buyer_id (buyer_id),
  CONSTRAINT fk_imf_shipping_fee_shipment FOREIGN KEY (shipment_id) REFERENCES game_trade_shipments (id),
  CONSTRAINT ck_imf_shipping_fee_amount CHECK (amount >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
}


def main(target):
    env_file, database = TARGETS[target]
    url = database_url(env_file)
    assert make_url(url).database == database
    engine = create_engine(url)
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    columns = {c['name'] for c in inspector.get_columns('game_trade_shipments')}
    with engine.begin() as connection:
        assert connection.execute(text('SELECT DATABASE()')).scalar() == database
        if 'legs' not in columns:
            connection.execute(text('ALTER TABLE game_trade_shipments ADD COLUMN legs JSON NULL'))
            print(f'{database}: dodano kolumnę game_trade_shipments.legs.')
        for name, ddl in TABLES.items():
            if name not in existing:
                connection.execute(text(ddl))
                print(f'{database}: utworzono tabelę {name}.')
    print(f'{database}: migracja dróg dostawy zakończona.')


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in TARGETS:
        raise SystemExit('Użycie: trade_delivery_20261122.py uat|preprod')
    main(sys.argv[1])
