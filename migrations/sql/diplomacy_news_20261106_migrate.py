"""Create the public diplomacy news ledger only in ZEUS UAT; no historical broadcast."""
from pathlib import Path
import sys
from sqlalchemy import create_engine,select,func,text
from sqlalchemy.engine import make_url


def migrate():
    root=Path(__file__).resolve().parents[2]
    assert root==Path('/home/oskar_zeus_admin/ZEUS_UAT');sys.path.insert(0,str(root))
    settings=dict(line.split('=',1) for line in (root/'.env.uat').read_text().splitlines() if line and not line.startswith('#') and '=' in line)
    url=settings['DATABASE_URL'].strip().strip('\"\'');assert make_url(url).database=='entenda_uat_db'
    from game.diplomacy_news import NewsControl,NewsBaseline,NewsEvent,NewsNotice
    from game.diplomacy_models import DiplomaticAction
    from models import AudytStosunki,Stosunki
    engine=create_engine(url,hide_parameters=True)
    with engine.begin() as connection:
        assert connection.scalar(text('SELECT DATABASE()'))=='entenda_uat_db'
        for model in (NewsControl,NewsBaseline,NewsEvent,NewsNotice):model.__table__.create(connection,checkfirst=True)
        if connection.scalar(select(NewsControl.id).where(NewsControl.id==1)) is None:
            baseline={}
            for a,b,relation,state in connection.execute(select(Stosunki.PANSTWO_ID,Stosunki.PANSTWO_ID2,Stosunki.relacja_id,Stosunki.stan_id)):
                a,b=sorted((a,b));baseline[(a,b)]={'a':a,'b':b,'relation':relation,'state':state}
            if baseline:connection.execute(NewsBaseline.__table__.insert(),list(baseline.values()))
            connection.execute(NewsControl.__table__.insert().values(id=1,audit_start=connection.scalar(select(func.coalesce(func.max(AudytStosunki.id),0))),action_start=connection.scalar(select(func.coalesce(func.max(DiplomaticAction.id),0)))))
    print('UAT: public diplomacy news tables and baseline ready; no historical notifications sent.')

if __name__=='__main__':migrate()
