"""UAT-only sea routes, merchant health and combat targets; no changes to payments/cargo."""
from pathlib import Path
import sys,json
from datetime import timedelta
from sqlalchemy import create_engine,text,inspect
from sqlalchemy.engine import make_url


def migrate():
    root=Path(__file__).resolve().parents[2];assert root==Path('/home/oskar_zeus_admin/ZEUS_UAT');sys.path.insert(0,str(root))
    settings=dict(line.split('=',1) for line in (root/'.env.uat').read_text().splitlines() if line and not line.startswith('#') and '=' in line)
    url=settings['DATABASE_URL'].strip().strip('\"\'');assert make_url(url).database=='entenda_uat_db'
    engine=create_engine(url,hide_parameters=True)
    with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as connection:
        assert connection.scalar(text('SELECT DATABASE()'))=='entenda_uat_db'
        columns={c['name'] for c in inspect(connection).get_columns('game_trade_shipments')}
        for name,definition in [('route','JSON NULL'),('health','INT NOT NULL DEFAULT 100'),('sunk_at','DATETIME NULL'),('origin_country_id','INT NULL')]:
            if name not in columns:connection.exec_driver_sql(f'ALTER TABLE game_trade_shipments ADD COLUMN {name} {definition}')
        if 'ck_trade_ship_health' not in {c['name'] for c in inspect(connection).get_check_constraints('game_trade_shipments')}:connection.exec_driver_sql('ALTER TABLE game_trade_shipments ADD CONSTRAINT ck_trade_ship_health CHECK (health BETWEEN 0 AND 100)')
        if 'target_shipment_id' not in {c['name'] for c in inspect(connection).get_columns('game_military_flights')}:connection.exec_driver_sql('ALTER TABLE game_military_flights ADD COLUMN target_shipment_id INT NULL, ADD CONSTRAINT fk_flight_target_shipment FOREIGN KEY (target_shipment_id) REFERENCES game_trade_shipments(id) ON DELETE SET NULL')
        connection.exec_driver_sql('UPDATE game_trade_shipments s JOIN miasta p ON p.miasto_id=s.departure_port_id SET s.origin_country_id=p.panstwo_id WHERE s.origin_country_id IS NULL')
    from game.sea_routes import shortest_sea_route,path_length
    from game.military_geography import city_point
    from engine.clock import get_current_entenda_datetime
    with engine.connect() as connection:
        scale=connection.scalar(text('SELECT km_per_unit FROM game_map_calibration WHERE id=1'))
        if scale is None or scale<=0:raise RuntimeError('Missing map calibration')
        rows=connection.execute(text('SELECT id,seller_id,buyer_id,departure_port_id,arrival_port_id FROM game_trade_shipments WHERE delivered_at IS NULL AND sunk_at IS NULL AND route IS NULL ORDER BY id')).mappings().all()
    changed=0
    for row in rows:
        route=shortest_sea_route(city_point(row['departure_port_id']),city_point(row['arrival_port_id']));distance=path_length(route)*float(scale)
        with engine.begin() as connection:
            actors=sorted({row['seller_id'],row['buyer_id']})
            for actor in actors:connection.execute(text('SELECT PANSTWO_ID FROM panstwa WHERE PANSTWO_ID=:id FOR UPDATE'),{'id':actor})
            current=connection.execute(text('SELECT starts_at,arrives_at,delivered_at,route FROM game_trade_shipments WHERE id=:id FOR UPDATE'),{'id':row['id']}).mappings().one()
            if current['delivered_at'] is not None or current['route'] is not None:continue
            now=get_current_entenda_datetime();arrival=current['arrives_at']
            # Already completed transit is never delayed. Active voyages get their true sea-distance ETA.
            if arrival>now:arrival=current['starts_at']+timedelta(seconds=max(1,distance/100*3600))
            connection.execute(text('UPDATE game_trade_shipments SET route=:route,source_x=:sx,source_y=:sy,target_x=:tx,target_y=:ty,distance_km=:distance,arrives_at=:arrival WHERE id=:id'),dict(route=json.dumps(route),sx=route[0][0],sy=route[0][1],tx=route[-1][0],ty=route[-1][1],distance=distance,arrival=arrival,id=row['id']))
            changed+=1
        print(f'UAT sea route recorded for shipment #{row["id"]}',flush=True)
    print(f'UAT merchant schema verified; {changed} water-only routes recorded. Cargo, payments and reserves unchanged.')


if __name__=='__main__':migrate()
