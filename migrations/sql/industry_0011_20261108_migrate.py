"""UAT-only additive industry migration; no application/scheduler import."""
import json,sys
from pathlib import Path
from sqlalchemy import create_engine,text,inspect,select
from sqlalchemy.engine import make_url

def migrate():
    root=Path(__file__).resolve().parents[2];assert root==Path('/home/oskar_zeus_admin/ZEUS_UAT');sys.path.insert(0,str(root))
    settings=dict(line.split('=',1) for line in (root/'.env.uat').read_text().splitlines() if line and not line.startswith('#') and '=' in line)
    url=settings['DATABASE_URL'].strip().strip('\"\'');assert make_url(url).database=='entenda_uat_db'
    import models
    import game.finance_models,game.commerce_models,game.research_models,game.military_models,game.intelligence_models
    from game.industry_models import PowerPlant,IndustryClock,IndustryMovement
    from game.industry_catalog import TECHNOLOGIES
    engine=create_engine(url,hide_parameters=True)
    with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as c:
        assert c.scalar(text('SELECT DATABASE()'))=='entenda_uat_db'
        c.exec_driver_sql('CREATE TABLE IF NOT EXISTS game_industry_migration (version VARCHAR(40) PRIMARY KEY, applied_at DATETIME NOT NULL) ENGINE=InnoDB')
        if c.scalar(text("SELECT COUNT(*) FROM game_industry_migration WHERE version='0011-20261108'")):
            print('Industry migration already applied.');return
        # Keep a JSON snapshot of touched data for review/recovery, outside the public tree.
        backup=root/'backups'/'industry_0011_20261108';backup.mkdir(parents=True,exist_ok=True)
        for table in ['game_research_accounts','game_mines','game_ammunition_factories','dict_zasoby']:
            rows=[dict(row._mapping) for row in c.execute(text('SELECT * FROM '+table))]
            path=backup/(table+'.json')
            if not path.exists():path.write_text(json.dumps(rows,ensure_ascii=False,default=str,indent=2));path.chmod(0o600)
        reserves=list(c.execute(text('SELECT panstwo_id,reserve_balance FROM game_state_financial_accounts ORDER BY panstwo_id')))
        for model in [PowerPlant,IndustryClock,IndustryMovement]:model.__table__.create(c,checkfirst=True)
        additions={
        'game_mines':{'level':'INT NOT NULL DEFAULT 1','removed_at':'DATETIME NULL','investment':'DECIMAL(29,2) NOT NULL DEFAULT 0'},
        'game_ammunition_factories':{'kind':"VARCHAR(32) NOT NULL DEFAULT 'interceptor_ammo'",'paused':'BOOLEAN NOT NULL DEFAULT 0','removed_at':'DATETIME NULL','production_progress':'INT NOT NULL DEFAULT 0','cycle_days':'INT NOT NULL DEFAULT 0','running':'BOOLEAN NOT NULL DEFAULT 0','ever_worked':'BOOLEAN NOT NULL DEFAULT 0'},
        'game_military_flights':{'target_power_id':'INT NULL'}}
        for table,columns in additions.items():
            present={column['name'] for column in inspect(c).get_columns(table)}
            for name,definition in columns.items():
                if name not in present:c.exec_driver_sql(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
        if not any(fk.get('constrained_columns')==['target_power_id'] for fk in inspect(c).get_foreign_keys('game_military_flights')):c.exec_driver_sql('ALTER TABLE game_military_flights ADD CONSTRAINT fk_flight_power FOREIGN KEY (target_power_id) REFERENCES game_power_plants(id) ON DELETE SET NULL')
        drop='DROP CONSTRAINT' if 'mariadb' in c.scalar(text('SELECT VERSION()')).lower() else 'DROP CHECK'
        for table,name,clause in [
            ('game_missile_defenses','ck_missile_defense_kind',"target_kind IN ('region','city','base','mine','factory','power')"),
            ('game_intelligence_missions','ck_intelligence_mission_kind',"kind IN ('bases','defenses','nuclear','resources','infrastructure','silos','mines','cyber_energy','cyber_rail','cyber_port','arson','rail_explosive','power')")]:
            previous=next((rule for rule in inspect(c).get_check_constraints(table) if rule['name'].startswith(name)),None)
            if previous and "'power'" not in previous['sqltext']:
                actual_name=previous['name']
                c.exec_driver_sql(f'ALTER TABLE {table} {drop} {actual_name}, ADD CONSTRAINT {name} CHECK ({clause})')
        for code,label in [('uran','Uran'),('zelazo','Żelazo')]:
            rows=list(c.execute(text('SELECT zasob_id FROM dict_zasoby WHERE zasob_kod=:code OR zasob_nazwa=:label'),dict(code=code,label=label)))
            if not rows:c.execute(text("INSERT INTO dict_zasoby (zasob_kod,zasob_nazwa,zasob_kategoria,zasob_jednostka,cena_bazowa,czy_strategiczny,czy_wydobywalny) VALUES (:code,:label,'Surowce naturalne','jednostka',0,'TAK','TAK')"),dict(code=code,label=label))
            elif len(rows)!=1:raise RuntimeError('Duplicate mineral entries require review.')
        # Preserve researched legacy method and ammo; refund only paid surplus points.
        costs=[10,15,30,50,100,200,500]
        for row in c.execute(text('SELECT panstwo_id,nodes,points FROM game_research_accounts')):
            nodes=json.loads(row.nodes) if isinstance(row.nodes,str) else dict(row.nodes or {})
            old_method=int(nodes.get('method',0));old_ammo=int(nodes.get('interceptor_ammo',0));refund=0
            if old_method>=10:
                nodes['method']=25;refund+=max(0,old_method-25)
            if old_ammo>=20:
                nodes['interceptor_ammo']=20;nodes['method']=25;nodes['arms_industry']=25
            c.execute(text('UPDATE game_research_accounts SET nodes=:nodes,points=points+:refund WHERE panstwo_id=:id'),dict(nodes=json.dumps(nodes),refund=refund,id=row.panstwo_id))
        # Stop retroactive settlement at the cutover; preserve original costs and history.
        from datetime import datetime
        from engine.clock import get_current_entenda_datetime
        clock=c.execute(text('SELECT real_anchor,entenda_anchor,multiplier FROM wiki_simulation_clock WHERE id=1')).first()
        now=clock.entenda_anchor+(datetime.now()-clock.real_anchor)*clock.multiplier if clock else get_current_entenda_datetime()
        c.execute(text('UPDATE game_ammunition_factories SET produced_at=:now'),dict(now=now))
        c.exec_driver_sql('UPDATE game_mines m SET investment=COALESCE((SELECT SUM(e.amount) FROM game_mining_expenses e WHERE e.mine_id=m.id),0) WHERE investment=0')
        c.execute(text('UPDATE game_mines SET extracted_at=GREATEST(extracted_at,:now)'),dict(now=now))
        assert reserves==list(c.execute(text('SELECT panstwo_id,reserve_balance FROM game_state_financial_accounts ORDER BY panstwo_id')))
        c.exec_driver_sql("INSERT INTO game_industry_migration VALUES ('0011-20261108',UTC_TIMESTAMP())")
        print('UAT industry schema and uranium/iron dictionary ready; reserve balances unchanged; research and legacy objects preserved.')
if __name__=='__main__':migrate()
