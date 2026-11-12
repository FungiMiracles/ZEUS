"""PAGA MULTI-AI fix (UAT only): Gemini free quotas are per MODEL, not per provider.

    venv/bin/python migrations/sql/paga_multi_ai_models_20261110.py            # backup + migrate
    venv/bin/python migrations/sql/paga_multi_ai_models_20261110.py --rollback # restore the backed-up rows, narrow the column

Widens game_paga_ai_providers.provider to VARCHAR(64) (keys 'gemini:<model>' hold per-model pauses) and moves the
provider-wide Gemini pause set by the first version (HTTP 429 of gemini-3.6-flash, until the daily reset) to that model,
so the other free Gemini models can answer. Touches only this PAGA table; no game data, no switches, no keys.
"""
from pathlib import Path
from datetime import datetime,timezone
import sys,json,argparse
from sqlalchemy import inspect,text
from sqlalchemy.engine import make_url

ROOT=Path(__file__).resolve().parents[2]
TABLE='game_paga_ai_providers'
LIMITED_MODEL='gemini:gemini-3.6-flash'


def make_app():
    assert ROOT==Path('/home/oskar_zeus_admin/ZEUS_UAT');sys.path.insert(0,str(ROOT))
    from flask import Flask
    from extensions import db
    settings=dict(line.split('=',1) for line in (ROOT/'.env.uat').read_text().splitlines() if line and not line.startswith('#') and '=' in line)
    url=settings['DATABASE_URL'].strip().strip('"\'');assert make_url(url).database=='entenda_uat_db','Migracja wyłącznie dla bazy UAT.'
    app=Flask('paga-multi-ai-models-migration',root_path=str(ROOT));app.config.update(SQLALCHEMY_DATABASE_URI=url,SQLALCHEMY_ENGINE_OPTIONS={'hide_parameters':True},ENV_NAME='UAT')
    db.init_app(app);return app


def rows(connection):return [dict(row) for row in connection.execute(text(f'SELECT * FROM `{TABLE}`')).mappings()]


def migrate():
    app=make_app()
    from extensions import db
    with app.app_context(),db.engine.begin() as connection:
        before=rows(connection)
        target=ROOT/'backups'/f'paga_multi_ai_models_before_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json'
        target.write_text(json.dumps(before,ensure_ascii=False,default=str,indent=1));print('Kopia zapasowa:',target,len(before),'wierszy')
        length=next(column['type'].length for column in inspect(connection).get_columns(TABLE) if column['name']=='provider')
        if length<64:connection.execute(text(f'ALTER TABLE `{TABLE}` MODIFY `provider` VARCHAR(64) NOT NULL'));print('Poszerzono kolumnę provider do 64 znaków.')
        row=connection.execute(text(f"SELECT cooldown_until,last_error FROM `{TABLE}` WHERE provider='gemini'")).first()
        if row and row.cooldown_until and 'HTTP 429' in (row.last_error or ''):
            connection.execute(text(f"INSERT INTO `{TABLE}` (provider,cooldown_until,last_error,updated_at) VALUES (:p,:u,'HTTP 429 — limit modelu',UTC_TIMESTAMP()) "
                                    "ON DUPLICATE KEY UPDATE cooldown_until=VALUES(cooldown_until),last_error=VALUES(last_error),updated_at=VALUES(updated_at)"),{'p':LIMITED_MODEL,'u':row.cooldown_until})
            connection.execute(text(f"UPDATE `{TABLE}` SET cooldown_until=NULL,last_error='Przerwę przeniesiono na model gemini-3.6-flash (limity liczone osobno dla modeli).',updated_at=UTC_TIMESTAMP() WHERE provider='gemini'"))
            print(f'Przerwę Gemini do {row.cooldown_until} UTC przeniesiono na {LIMITED_MODEL}; pozostałe darmowe modele Gemini są dostępne.')
        print('Gotowe.')


def rollback():
    app=make_app()
    from extensions import db
    backups=sorted((ROOT/'backups').glob('paga_multi_ai_models_before_*.json'))
    assert backups,'Brak kopii zapasowej.'
    data=json.loads(backups[-1].read_text())
    with app.app_context(),db.engine.begin() as connection:
        connection.execute(text(f'DELETE FROM `{TABLE}`'))
        for row in data:connection.execute(text(f'INSERT INTO `{TABLE}` (provider,cooldown_until,last_error,updated_at) VALUES (:provider,:cooldown_until,:last_error,:updated_at)'),row)
        connection.execute(text(f'ALTER TABLE `{TABLE}` MODIFY `provider` VARCHAR(16) NOT NULL'))
        print('Przywrócono',len(data),'wierszy z',backups[-1].name)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--rollback',action='store_true');args=parser.parse_args()
    rollback() if args.rollback else migrate()
