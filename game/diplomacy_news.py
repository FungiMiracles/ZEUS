"""Public third-country diplomacy news, durable delivery and independent read status."""
from flask import current_app,jsonify,request,url_for
from sqlalchemy import select,exists,func,literal,cast,String
from sqlalchemy.orm import Session
from extensions import db
from game.models import GameUser,GamePlayerCountry,utc_now
from game.forum_models import GameNotification
from models import Panstwo,AudytStosunki,DictStosunkiRelacja,DictStosunkiStan
from services.natural_resources import normalized


class NewsControl(db.Model):
    __tablename__='game_diplomacy_news_control'
    id=db.Column(db.Integer,primary_key=True)
    audit_start=db.Column(db.Integer,nullable=False)
    action_start=db.Column(db.Integer,nullable=False)
    __table_args__={'mysql_engine':'InnoDB'}


class NewsBaseline(db.Model):
    __tablename__='game_diplomacy_news_baseline'
    a=db.Column(db.Integer,primary_key=True)
    b=db.Column(db.Integer,primary_key=True)
    relation=db.Column(db.Integer)
    state=db.Column(db.Integer)
    __table_args__={'mysql_engine':'InnoDB'}


class NewsEvent(db.Model):
    __tablename__='game_diplomacy_news_events'
    id=db.Column(db.Integer,primary_key=True)
    source_key=db.Column(db.String(80),nullable=False,unique=True)
    kind=db.Column(db.String(32),nullable=False)
    a=db.Column(db.Integer,nullable=False)
    b=db.Column(db.Integer,nullable=False)
    name_a=db.Column(db.String(255),nullable=False)
    name_b=db.Column(db.String(255),nullable=False)
    text=db.Column(db.String(1000),nullable=False)
    game_at=db.Column(db.DateTime,nullable=False)
    created_at=db.Column(db.DateTime,nullable=False,default=utc_now)
    __table_args__={'mysql_engine':'InnoDB'}


class NewsNotice(db.Model):
    __tablename__='game_diplomacy_news_notices'
    user_id=db.Column(db.Integer,db.ForeignKey('game_users.id'),primary_key=True)
    event_id=db.Column(db.Integer,db.ForeignKey('game_diplomacy_news_events.id'),primary_key=True)
    main_notification_id=db.Column(db.Integer,db.ForeignKey('game_notifications.id'),unique=True)
    read_at=db.Column(db.DateTime)
    __table_args__={'mysql_engine':'InnoDB'}


def enabled():return current_app.config.get('DIPLOMACY_NEWS_ENABLED',False) and current_app.config.get('ENV_NAME')=='UAT'


def lock_control(session):
    row=session.scalar(select(NewsControl).where(NewsControl.id==1).with_for_update())
    if row is None:raise RuntimeError('Brak migracji powiadomień dyplomatycznych UAT.')
    return row


def publish(session,key,kind,a,b,text,game_at,names=None):
    existing=session.scalar(select(NewsEvent).where(NewsEvent.source_key==key))
    if existing:return existing
    if names is None:names=dict(session.execute(select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa).where(Panstwo.PANSTWO_ID.in_([a,b]))).all())
    event=NewsEvent(source_key=key,kind=kind,a=a,b=b,name_a=names.get(a,str(a)),name_b=names.get(b,str(b)),text=text,game_at=game_at)
    session.add(event);session.flush()
    if kind=='UNCHANGED':return event
    for user_id in session.scalars(select(GameUser.id).join(GamePlayerCountry,GamePlayerCountry.user_id==GameUser.id).where(GameUser.is_active.is_(True),GamePlayerCountry.panstwo_id.notin_([a,b])).order_by(GameUser.id)):
        notice=NewsNotice(user_id=user_id,event_id=event.id);session.add(notice)
        if kind in ('WAR_STARTED','WAR_ENDED'):
            main=GameNotification(user_id=user_id,notification_type='SYSTEM',system_text=text)
            session.add(main);session.flush();notice.main_notification_id=main.id
    session.flush();return event


def record_change(session,audit,old_relation,old_state):
    if not enabled():return
    lock_control(session)
    names=dict(session.execute(select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa).where(Panstwo.PANSTWO_ID.in_([audit.panstwo_id,audit.panstwo_id2]))).all())
    relations=dict(session.execute(select(DictStosunkiRelacja.relacja_id,DictStosunkiRelacja.relacja_nazwa)).all())
    states=dict(session.execute(select(DictStosunkiStan.stan_id,DictStosunkiStan.stan_nazwa)).all())
    a,b=audit.panstwo_id,audit.panstwo_id2;one=names.get(a,str(a));two=names.get(b,str(b))
    before=normalized(states.get(old_state,''));after=normalized(states.get(audit.stan_id,''))
    war=lambda value:value.startswith('wojna')
    changes=[];kind='UNCHANGED'
    if old_relation!=audit.relacja_id:
        kind='RELATION_CHANGED';changes.append(f'zmiana relacji z „{relations.get(old_relation,"brak danych")}” na „{relations.get(audit.relacja_id,"brak danych")}”')
    if old_state!=audit.stan_id:
        kind='STATE_CHANGED';changes.append(f'zmiana stanu stosunków z „{states.get(old_state,"brak danych")}” na „{states.get(audit.stan_id,"brak danych")}”')
    text=f'{one} — {two}: '+('; '.join(changes) or 'bez zmiany stosunków')+'.'
    if war(after) and (not war(before) or after=='wojnakinetyczna' and before!=after):kind='WAR_STARTED';text=f'{one} i {two}: rozpoczęła się wojna. Stan stosunków: {states.get(audit.stan_id)}.'
    elif (war(before) or before in ('zawieszeniebroni','okupacja')) and after=='pokoj':kind='WAR_ENDED';text=f'{one} i {two}: wojna została zakończona. Stan stosunków: {states.get(audit.stan_id)}.'
    return publish(session,f'audit:{audit.id}',kind,a,b,text,audit.data_zmiany_entenda,names)


def record_rejection(session,action,now):
    if not enabled() or action.kind!='RELATION' or action.status!='REJECTED':return
    lock_control(session)
    relation=session.scalar(select(DictStosunkiRelacja.relacja_nazwa).where(DictStosunkiRelacja.relacja_id==action.proposed_relation_id)) or 'brak danych'
    text=f'{action.target_country_name}: odrzucono propozycję zmiany relacji na „{relation}” od państwa {action.source_country_name}.'
    return publish(session,f'reject:{action.id}','PROPOSAL_REJECTED',action.target_country_id,action.source_country_id,text,now,{action.target_country_id:action.target_country_name,action.source_country_id:action.source_country_name})


def collect(session,now):
    if not enabled():return
    from game.diplomacy_models import DiplomaticAction
    control=lock_control(session)
    for audit in session.scalars(select(AudytStosunki).where(AudytStosunki.id>control.audit_start,~exists(select(NewsEvent.id).where(NewsEvent.source_key==(literal('audit:')+cast(AudytStosunki.id,String))))).order_by(AudytStosunki.id).limit(200)):
        previous=session.execute(select(AudytStosunki.relacja_id,AudytStosunki.stan_id).where(AudytStosunki.panstwo_id==audit.panstwo_id,AudytStosunki.panstwo_id2==audit.panstwo_id2,AudytStosunki.id<audit.id).order_by(AudytStosunki.id.desc()).limit(1)).first()
        baseline=session.get(NewsBaseline,tuple(sorted((audit.panstwo_id,audit.panstwo_id2))))
        from game.diplomacy_service import dictionaries
        _,states,neutral=dictionaries(session)
        record_change(session,audit,previous.relacja_id if previous else baseline.relation if baseline else neutral,previous.stan_id if previous else baseline.state if baseline else states['pokoj'])
    for action in session.scalars(select(DiplomaticAction).where(DiplomaticAction.id>control.action_start,DiplomaticAction.kind=='RELATION',DiplomaticAction.status=='REJECTED',~exists(select(NewsEvent.id).where(NewsEvent.source_key==(literal('reject:')+cast(DiplomaticAction.id,String))))).order_by(DiplomaticAction.id).limit(200)):
        record_rejection(session,action,now)


def run_news_tick(app):
    with app.app_context():
        if not enabled():return
        from game.finance_service import game_now
        try:
            with Session(db.engine) as session,session.begin():collect(session,game_now())
        except Exception:app.logger.exception('Powiadomienia o dyplomacji świata: błąd zbierania zdarzeń.')


def query_for(user_id,country_id):
    return select(NewsNotice,NewsEvent).join(NewsEvent,NewsEvent.id==NewsNotice.event_id).where(NewsNotice.user_id==user_id,NewsEvent.a!=country_id,NewsEvent.b!=country_id)


def unread_count(user_id,country_id):
    return db.session.scalar(select(func.count()).select_from(query_for(user_id,country_id).where(NewsNotice.read_at.is_(None)).subquery()))


def feed(user,country):
    page=max(1,request.args.get('page',1,type=int) or 1)
    rows=list(db.session.execute(query_for(user.id,country.PANSTWO_ID).order_by(NewsEvent.id.desc()).offset((page-1)*20).limit(21)))
    flag=lambda name:url_for('static',filename='flags/'+name.replace(' ','_')+'.jpg')
    response=jsonify(unread_count=unread_count(user.id,country.PANSTWO_ID),next_page=page+1 if len(rows)>20 else None,items=[{'id':event.id,'text':event.text,'kind':event.kind,'unread':notice.read_at is None,'severity':'war' if event.kind=='WAR_STARTED' else 'info','gameAt':event.game_at.isoformat(),'flags':[{'name':event.name_a,'url':flag(event.name_a)},{'name':event.name_b,'url':flag(event.name_b)}]} for notice,event in rows[:20]])
    response.headers['Cache-Control']='no-store';return response
