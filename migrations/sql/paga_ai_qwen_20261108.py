"""Add isolated AI player identities and persistent control; OFF until explicitly enabled."""
from pathlib import Path
import sys
from sqlalchemy import create_engine,select,func
from sqlalchemy.engine import make_url

def make_app():
    root=Path(__file__).resolve().parents[2];assert root==Path('/home/oskar_zeus_admin/ZEUS_UAT');sys.path.insert(0,str(root))
    from flask import Flask
    from extensions import db
    import models,game.models
    settings=dict(line.split('=',1) for line in (root/'.env.uat').read_text().splitlines() if line and not line.startswith('#') and '=' in line)
    url=settings['DATABASE_URL'].strip().strip('\"\'');assert make_url(url).database=='entenda_uat_db'
    app=Flask('paga-ai-migration',root_path=str(root));app.config.update(SQLALCHEMY_DATABASE_URI=url,SQLALCHEMY_ENGINE_OPTIONS={'hide_parameters':True},PAGA_ENABLED=True,ENV_NAME='UAT',PAGA_AI_CONFIGURED=True,ENTENDA_CLOCK_CONTROL_ENABLED=True)
    db.init_app(app);return app

def migrate():
    app=make_app()
    from extensions import db
    from game.paga_ai_models import PagaAiControl,PagaAiIdentity,PagaAiJob,PagaAiLog
    from game.paga_ai_actor import ensure_identity
    from game.autonomy_engine import eligible_ids
    from game.autonomy_models import AutonomyEvent
    from game.forum_models import ForumMessage
    from game.communication_models import PrivateMessage
    with app.app_context():
        for model in [PagaAiControl,PagaAiIdentity,PagaAiJob,PagaAiLog]:model.__table__.create(db.engine,checkfirst=True)
        control=db.session.get(PagaAiControl,1)
        if control is None:
            control=PagaAiControl(id=1,enabled=False,revision=0,model_id='Qwen3.5-4B-Q4_K_M',event_cursor=db.session.scalar(select(func.max(AutonomyEvent.id))) or 0,forum_cursor=db.session.scalar(select(func.max(ForumMessage.id))) or 0,private_cursor=db.session.scalar(select(func.max(PrivateMessage.id))) or 0);db.session.add(control)
        ids=eligible_ids(db.session)
        for id in ids:ensure_identity(db.session,id)
        db.session.commit()
        print('UAT schema ready. AI enabled:',control.enabled,'AI state identities:',len(ids),'No human assignments changed.')
if __name__=='__main__':migrate()
