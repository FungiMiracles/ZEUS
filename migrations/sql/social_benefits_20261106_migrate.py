"""Create social-benefit records exclusively in ZEUS_UAT."""
from pathlib import Path
import sys
from sqlalchemy import create_engine,text
from sqlalchemy.engine import make_url


def migrate():
    root=Path(__file__).resolve().parents[2]
    assert root==Path('/home/oskar_zeus_admin/ZEUS_UAT')
    sys.path.insert(0,str(root))
    settings=dict(line.split('=',1) for line in (root/'.env.uat').read_text().splitlines() if line and not line.startswith('#') and '=' in line)
    url=settings['DATABASE_URL'].strip().strip('\"\'')
    assert make_url(url).database=='entenda_uat_db'
    import models
    import game.finance_models
    from game.social_benefits import BenefitPayment,BenefitSettlement,MissedBenefitPeriod
    engine=create_engine(url,hide_parameters=True)
    with engine.begin() as connection:
        assert connection.scalar(text('SELECT DATABASE()'))=='entenda_uat_db'
        for model in (BenefitPayment,BenefitSettlement,MissedBenefitPeriod):model.__table__.create(connection,checkfirst=True)
    print('UAT: benefit payment and settlement tables verified.')

if __name__=='__main__':migrate()
