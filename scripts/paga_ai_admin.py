"""UAT operator CLI, using the real app with schedulers suppressed for this process."""
from pathlib import Path
import contextlib,io,json,os,sys,argparse
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
def make_app():
    assert ROOT==Path('/home/oskar_zeus_admin/ZEUS_UAT')
    for line in (ROOT/'.env.uat').read_text().splitlines():
        if line and not line.startswith('#') and '=' in line:
            key,value=line.split('=',1);os.environ[key]=value.strip().strip('\"\'')
    os.environ['ENV_NAME']='UAT'
    with contextlib.redirect_stdout(io.StringIO()):
        with patch('engine.generator.start_event_scheduler'),patch('engine.infrastructure_scheduler.start_infrastructure_scheduler'),patch('engine.finance_scheduler.start_finance_scheduler'),patch('engine.autonomy_scheduler.start_autonomy_scheduler'),patch('engine.paga_ai_scheduler.start_paga_ai_scheduler'):
            from zeus_app import app
    assert app.config['ENV_NAME']=='UAT'
    from sqlalchemy.engine import make_url
    assert make_url(app.config['SQLALCHEMY_DATABASE_URI']).database=='entenda_uat_db'
    return app

def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['status','enable','disable','tick','catalogue'],nargs='?',default='status');args=parser.parse_args();app=make_app()
    from extensions import db
    from sqlalchemy import select,func
    from game.paga_ai_models import PagaAiControl,PagaAiIdentity,PagaAiJob
    from game.player_operations import catalogue
    from engine.paga_ai_scheduler import toggle,run_tick
    if args.action=='tick':run_tick(app)
    with app.app_context():
        control=db.session.get(PagaAiControl,1)
        if args.action in ['enable','disable']:toggle(db.session,args.action=='enable',control.revision);db.session.commit();db.session.refresh(control)
        if args.action=='catalogue':
            print(json.dumps([row.public() for row in catalogue(app).values()],ensure_ascii=False,indent=2));return
        print(json.dumps({'enabled':control.enabled,'revision':control.revision,'model':control.model_id,'identities':db.session.scalar(select(func.count()).select_from(PagaAiIdentity)),'operations':len(catalogue(app)),'queue':dict(db.session.execute(select(PagaAiJob.status,func.count()).group_by(PagaAiJob.status)).all()),'modelReady':(ROOT/'runtime/qwen/MODEL.json').is_file()},ensure_ascii=False))
if __name__=='__main__':main()
