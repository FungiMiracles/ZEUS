"""UAT-only PAGA: WIKI 'wszechmocny' role, no extra password; CSRF-bound access token inside the panel."""
import hmac,secrets
from flask import Blueprint,current_app,request,session,abort,jsonify,render_template,url_for
from itsdangerous import URLSafeTimedSerializer,BadSignature,SignatureExpired
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from extensions import db
from models import Panstwo,DictKontynent
from game.paga import TRAITS,INTERESTS,PagaConfiguration,configuration_data,save_configuration,PagaError,PagaConflict

paga_bp=Blueprint('paga',__name__,url_prefix='/admin/paga')
ACCESS_SECONDS=12*3600  # a long working session; re-opening the page issues a new token


def serializer():return URLSafeTimedSerializer(current_app.secret_key,salt='paga-access-v1')


@paga_bp.before_request
def restrict():
    if not current_app.config.get('PAGA_ENABLED'):abort(404)
    if session.get('rola')!='wszechmocny':abort(403)


@paga_bp.after_request
def no_cache(response):
    response.headers['Cache-Control']='no-store'
    response.headers['Referrer-Policy']='same-origin'
    return response


def check_access():
    supplied=request.headers.get('X-CSRF-Token','');expected=session.get('paga_api_csrf','')
    if not expected or not hmac.compare_digest(supplied.encode(),expected.encode()):abort(403)
    try:proof=serializer().loads(request.headers.get('X-PAGA-Access',''),max_age=ACCESS_SECONDS)
    except (BadSignature,SignatureExpired):abort(403,description='Sesja PAGA wygasła. Odśwież stronę PAGA.')
    if not isinstance(proof,dict) or proof.get('csrf')!=expected:abort(403)


def paga2_map_url():
    from werkzeug.routing import BuildError
    try:return url_for('region_sovereignty.country_boundaries')
    except BuildError:return None


@paga_bp.route('',methods=['GET','POST'])
def entry():
    """No separate PAGA password: the logged-in WIKI 'wszechmocny' role (checked in restrict) opens the panel."""
    session.setdefault('paga_api_csrf',secrets.token_urlsafe(32))
    csrf=session['paga_api_csrf']
    monitoring=current_app.config.get('PAGA_AI_CONFIGURED') and current_app.config.get('ENV_NAME')=='UAT'
    config={'monitoringUrl':url_for('paga.monitoring_decisions') if monitoring else None,'monitoringDetailUrl':url_for('paga.monitoring_decision',key='KEY') if monitoring else None,
            'monitoringCountriesUrl':url_for('paga.monitoring_countries') if monitoring else None,'monitoringGoalsUrl':url_for('paga.monitoring_goals') if monitoring else None,
            'aiSettingsUrl':url_for('paga.ai_settings') if current_app.config.get('PAGA_AI_CONFIGURED') else None,'relationshipsUrl':url_for('paga.relationships'),'relationshipCountriesUrl':url_for('paga.relationship_countries'),'aiUrl':url_for('paga.ai_control') if current_app.config.get('PAGA_AI_CONFIGURED') else None,'csrf':csrf,'access':serializer().dumps({'csrf':csrf,'entry':secrets.token_urlsafe(16)}),
            'paga2':{'countriesUrl':url_for('paga.paga2_countries'),'countryUrl':url_for('paga.paga2_country',country_id=0),'controlUrl':url_for('paga.paga2_control'),
                     'decisionsUrl':url_for('paga.paga2_decisions'),'decisionUrl':url_for('paga.paga2_decision',decision_id=0),'stateUrl':url_for('paga.paga2_state',country_id=0),
                     'mapUrl':paga2_map_url(),'flagsUrl':url_for('static',filename='flags/'),'catalog':__import__('game.paga2.admin',fromlist=['catalog_data']).catalog_data()},
            'monitorUrl':url_for('paga.monitor'),'controlUrl':url_for('paga.control'),'countriesUrl':url_for('paga.countries'),'countryUrl':url_for('paga.country',country_id=0),'traits':TRAITS,'interests':INTERESTS}
    continents=list(db.session.execute(select(DictKontynent.kontynent_id,DictKontynent.kontynent_nazwa).order_by(DictKontynent.kontynent_nazwa)))
    return render_template('admin_paga.html',paga_config=config,continents=continents)


@paga_bp.get('/panstwa')
def countries():
    check_access()
    continent=request.args.get('continent',type=int)
    if continent is None:return jsonify(countries=[])
    query=select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa).where(Panstwo.kontynent_id==continent,Panstwo.status=='aktywne')
    search=request.args.get('q','').strip()[:255]
    if search:query=query.where(Panstwo.panstwo_nazwa.icontains(search,autoescape=True))
    return jsonify(countries=[{'id':id,'name':name} for id,name in db.session.execute(query.order_by(Panstwo.panstwo_nazwa))])


@paga_bp.route('/panstwo/<int:country_id>',methods=['GET','POST'])
def country(country_id):
    check_access()
    if country_id>2147483647:abort(404)
    if request.method=='POST':
        try:
            with Session(db.engine) as database_session,database_session.begin():
                state=save_configuration(database_session,country_id,request.get_json(silent=True),session.get('username') or 'Wszechmocny WIKI')
        except PagaConflict as error:return jsonify(error=str(error)),409
        except PagaError as error:return jsonify(error=str(error)),400
        return jsonify(configuration=state)
    row=db.session.execute(select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa,Panstwo.panstwo_pelna_nazwa).where(Panstwo.PANSTWO_ID==country_id,Panstwo.status=='aktywne')).first()
    if row is None:abort(404)
    return jsonify(country={'id':row[0],'name':row[1],'fullName':row[2] or row[1],'flag':url_for('static',filename='flags/'+(row[1] or '').replace(' ','_')+'.jpg')},configuration=configuration_data(db.session.get(PagaConfiguration,country_id)))


@paga_bp.get('/powiazania/panstwa')
def relationship_countries():
    check_access()
    return jsonify(countries=[{'id':id,'name':name} for id,name in db.session.execute(
        select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa).where(Panstwo.status=='aktywne').order_by(Panstwo.panstwo_nazwa)
    )])


@paga_bp.get('/powiazania')
def relationships():
    check_access()
    from game.paga_relationships import PagaRelationship, STATUSES, relationship_data
    countries=dict(db.session.execute(select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa).where(Panstwo.status=='aktywne')).all())
    page=max(1,min(10000,request.args.get('page',1,type=int) or 1))
    rows=list(db.session.scalars(select(PagaRelationship).where(
        PagaRelationship.status!='none',PagaRelationship.country_a_id.in_(countries),PagaRelationship.country_b_id.in_(countries)
    ).order_by(PagaRelationship.country_a_id,PagaRelationship.country_b_id).offset((page-1)*25).limit(26)))
    return jsonify(statuses=STATUSES,page=page,hasMore=len(rows)>25,relationships=[{
        **relationship_data(row),'first':{'id':row.country_a_id,'name':countries[row.country_a_id]},
        'second':{'id':row.country_b_id,'name':countries[row.country_b_id]}
    } for row in rows[:25]])


@paga_bp.route('/powiazania/<int:first>/<int:second>',methods=['GET','POST'])
def relationship(first,second):
    check_access()
    from game.paga_relationships import PagaRelationship, canonical_pair, relationship_data, save_relationship
    try:
        a,b=canonical_pair(first,second)
        if request.method=='POST':
            with Session(db.engine) as database,database.begin():
                data=save_relationship(database,a,b,request.get_json(silent=True),session.get('username') or 'Wszechmocny WIKI')
        else:
            ids=list(db.session.scalars(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID.in_((a,b)),Panstwo.status=='aktywne').order_by(Panstwo.PANSTWO_ID)))
            if ids!=[a,b]:raise PagaError('Oba państwa muszą istnieć i być aktywne.')
            data=relationship_data(db.session.get(PagaRelationship,(a,b),populate_existing=True))
        return jsonify(relationship=data)
    except PagaConflict as error:return jsonify(error=str(error)),409
    except PagaError as error:return jsonify(error=str(error)),400


@paga_bp.get('/monitor')
def monitor():
    check_access()
    from datetime import datetime,timedelta
    from game.autonomy_models import AutonomyControl,AutonomyAnalysis,AutonomySchedule,AutonomyReaction,AutonomyMemory,AutonomyEvent,AutonomyAssessment
    from game.models import GamePlayerCountry
    from game.autonomy_engine import eligible_ids
    from sqlalchemy import func
    control=db.session.get(AutonomyControl,1)
    if control is None:return jsonify(error='Silnik autonomii wymaga migracji bazy UAT.'),503
    query=select(AutonomyAnalysis)
    country_id=request.args.get('country',type=int)
    if country_id:query=query.where(AutonomyAnalysis.country_id==country_id)
    kind=request.args.get('kind','').strip()[:40]
    if kind:query=query.where(AutonomyAnalysis.action==kind)
    try:
        if request.args.get('from'):query=query.where(AutonomyAnalysis.game_at>=datetime.strptime(request.args['from'],'%Y-%m-%d'))
        if request.args.get('to'):query=query.where(AutonomyAnalysis.game_at<datetime.strptime(request.args['to'],'%Y-%m-%d')+timedelta(days=1))
    except ValueError:return jsonify(error='Podaj prawidłową datę Entendy.'),400
    page=max(1,min(10000,request.args.get('page',1,type=int) or 1))
    records=list(db.session.scalars(query.order_by(AutonomyAnalysis.id.desc()).offset((page-1)*25).limit(26)))
    countries=dict(db.session.execute(select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa).where(Panstwo.status=='aktywne').order_by(Panstwo.panstwo_nazwa)).all())
    eligible=set(eligible_ids(db.session));human=set(db.session.scalars(select(GamePlayerCountry.panstwo_id)))
    stamp=lambda value:value.isoformat()+'Z' if value else None
    schedules=[{'countryId':row.country_id,'country':countries.get(row.country_id),'nextAt':stamp(row.next_at),'lastAt':stamp(row.last_at),'error':row.last_error,'eligible':row.country_id in eligible,'human':row.country_id in human} for row in db.session.scalars(select(AutonomySchedule).order_by(AutonomySchedule.next_at))]
    memories=[];assessments=[]
    if country_id:
        for memory,event in db.session.execute(select(AutonomyMemory,AutonomyEvent).join(AutonomyEvent,AutonomyMemory.event_id==AutonomyEvent.id).where(AutonomyMemory.country_id==country_id).order_by(AutonomyEvent.id.desc()).limit(25)):
            memories.append({'eventId':event.id,'kind':event.kind,'date':stamp(event.occurred_at),'actor':event.actor_id,'target':event.target_id,'public':event.public,'importance':memory.importance,'payload':event.payload})
        assessments=[{'otherId':row.other_id,'country':countries.get(row.other_id),'trust':row.trust,'threat':row.threat,'confidence':row.confidence,'date':stamp(row.updated_at)} for row in db.session.scalars(select(AutonomyAssessment).where(AutonomyAssessment.country_id==country_id).order_by(AutonomyAssessment.other_id))]
    from game.intelligence_service import MISSIONS,HYBRID
    action_kinds=['PASSIVE','ERROR','WAR','PEACE','CEASEFIRE','ALLIANCE','PARTNERSHIP','RELATION_IMPROVE','RELATION_WORSEN','ACCEPT','REJECT','RECRUIT_AGENT']+[('HYBRID_' if kind in HYBRID else 'SCOUT_')+kind for kind in MISSIONS]
    return jsonify(actionKinds=sorted(action_kinds),control={'enabled':control.enabled,'revision':control.revision,'maxActions':control.max_actions,'windowDays':control.window_days,'cooldownDays':control.cooldown_days,'maxChainDepth':control.max_chain_depth,'startedAt':stamp(control.started_at),'actor':control.updated_actor},countries=[{'id':id,'name':name,'eligible':id in eligible,'human':id in human} for id,name in countries.items()],schedules=schedules,queued=db.session.scalar(select(func.count()).select_from(AutonomyReaction).where(AutonomyReaction.status=='READY')),page=page,hasMore=len(records)>25,analyses=[{'id':row.id,'countryId':row.country_id,'country':countries.get(row.country_id),'date':stamp(row.game_at),'trigger':row.trigger,'eventId':row.event_id,'action':row.action,'targetId':row.target_id,'target':countries.get(row.target_id),'score':row.score,'status':row.status,'factors':row.factors,'candidates':row.candidates,'result':row.result,'error':row.error} for row in records[:25]],memories=memories,assessments=assessments)


@paga_bp.post('/sterowanie')
def control():
    check_access()
    # Dotychczasowego silnika regułowego nie można już włączyć (decyzja administratora 11 Nov 2026) — zastąpił go PAGA2.
    from game.paga_ai_tasks import legacy_engines
    if not legacy_engines():return jsonify(error='Dotychczasowy silnik regułowy PAGA został wyłączony na stałe. Decyzje państw podejmuje PAGA2 (zakładka „Konfiguracja PAGA2”).'),410
    data=request.get_json(silent=True)
    if not isinstance(data,dict) or type(data.get('enabled')) is not bool or type(data.get('revision')) is not int:return jsonify(error='Nieprawidłowe sterowanie autonomią.'),400
    for key in ('maxActions','windowDays','cooldownDays'):
        if type(data.get(key)) is not int or not 1<=data[key]<=365:return jsonify(error='Limity muszą być liczbami całkowitymi od 1 do 365.'),400
    from game.autonomy_models import AutonomyControl
    with Session(db.engine) as database_session,database_session.begin():
        row=database_session.scalar(select(AutonomyControl).where(AutonomyControl.id==1).with_for_update())
        if row is None:return jsonify(error='Brak konfiguracji silnika.'),503
        if row.revision!=data['revision']:return jsonify(error='Sterowanie zmieniło się. Odśwież Monitor autonomii.'),409
        row.enabled=data['enabled'];row.max_actions=data['maxActions'];row.window_days=data['windowDays'];row.cooldown_days=data['cooldownDays'];row.revision+=1;row.updated_actor=str(session.get('username') or 'Wszechmocny WIKI')[:120]
    return jsonify(ok=True)


@paga_bp.route('/ai',methods=['GET','POST'])
def ai_control():
    check_access()
    if current_app.config.get('ENV_NAME')!='UAT' or not current_app.config.get('PAGA_AI_CONFIGURED'):abort(404)
    from game.paga_ai_models import PagaAiControl,PagaAiJob,PagaAiLog
    from engine.paga_ai_scheduler import toggle
    if request.method=='POST':
        data=request.get_json(silent=True)
        if not isinstance(data,dict) or type(data.get('enabled')) is not bool or type(data.get('revision')) is not int:return jsonify(error='Nieprawidłowe ustawienie AI.'),400
        try:
            with Session(db.engine) as database,database.begin():toggle(database,data['enabled'],data['revision'])
        except ValueError as error:return jsonify(error=str(error)),409
    row=db.session.get(PagaAiControl,1,populate_existing=True)
    if row is None:return jsonify(error='Nie wykonano migracji PAGA AI.'),503
    jobs=dict(db.session.execute(select(PagaAiJob.status,func.count()).group_by(PagaAiJob.status)).all())
    logs=[{'id':item.id,'countryId':item.country_id,'gameAt':item.game_at.isoformat(),'realAt':item.real_at.isoformat(),'operation':item.operation,'parameters':item.parameters,'validation':item.validation,'result':item.result,'reason':item.reason,'model':item.model_id} for item in db.session.scalars(select(PagaAiLog).order_by(PagaAiLog.id.desc()).limit(20))]
    from game.paga_ai_metrics import summary
    try:metrics=summary(db.session)
    except Exception:db.session.rollback();metrics=None
    from game.paga_ai_providers import status as provider_status
    try:providers=provider_status(db.session)
    except Exception:db.session.rollback();providers=None
    return jsonify(enabled=row.enabled,revision=row.revision,model=row.model_id,jobs=jobs,logs=logs,metrics=metrics,providers=providers,
                   settings={'reviewIntervalMinutes':row.review_interval_minutes,'maxModelCalls':row.max_model_calls})


@paga_bp.post('/ai/ustawienia')
def ai_settings():
    """Scheduling parameters only; never switches autonomy on or off."""
    check_access()
    if current_app.config.get('ENV_NAME')!='UAT' or not current_app.config.get('PAGA_AI_CONFIGURED'):abort(404)
    from game.paga_ai_models import PagaAiControl
    data=request.get_json(silent=True)
    if not isinstance(data,dict) or type(data.get('reviewIntervalMinutes')) is not int or not 15<=data['reviewIntervalMinutes']<=10080 \
       or type(data.get('maxModelCalls')) is not int or not 1<=data['maxModelCalls']<=5:
        return jsonify(error='Przegląd strategiczny: od 15 do 10080 minut; wywołania modelu na zadanie: od 1 do 5.'),400
    with Session(db.engine) as database,database.begin():
        row=database.scalar(select(PagaAiControl).where(PagaAiControl.id==1).with_for_update())
        if row is None:return jsonify(error='Nie wykonano migracji PAGA AI.'),503
        row.review_interval_minutes=data['reviewIntervalMinutes'];row.max_model_calls=data['maxModelCalls']
    return jsonify(ok=True)


# ---------------- Monitoring decyzji PAGA AI (UAT only, read-only, no model calls) ----------------

def monitoring_guard():
    check_access()
    if current_app.config.get('ENV_NAME')!='UAT' or not current_app.config.get('PAGA_AI_CONFIGURED'):abort(404)


def monitoring_filters():
    country=request.args.get('country',type=int)
    return {'country':country if country and 0<country<=2147483647 else None,'category':request.args.get('category','').strip()[:20] or None,
            'status':request.args.get('status','').strip()[:20] or None,'from':request.args.get('from','').strip()[:10] or None,'to':request.args.get('to','').strip()[:10] or None,
            'game_from':request.args.get('game_from','').strip()[:10] or None,'game_to':request.args.get('game_to','').strip()[:10] or None}


@paga_bp.get('/monitoring/decyzje')
def monitoring_decisions():
    monitoring_guard()
    from game.paga_ai_monitoring import registry,statistics
    filters=monitoring_filters()
    try:data=registry(db.session,filters,request.args.get('page',1,type=int) or 1)
    except ValueError as error:return jsonify(error=str(error)),400
    return jsonify(**data,statistics=statistics(db.session,filters['country']))


@paga_bp.get('/monitoring/decyzje/<key>')
def monitoring_decision(key):
    monitoring_guard()
    from game.paga_ai_monitoring import detail
    try:return jsonify(decision=detail(db.session,key))
    except ValueError as error:return jsonify(error=str(error)),400
    except LookupError:abort(404)


@paga_bp.get('/monitoring/panstwa')
def monitoring_countries():
    monitoring_guard()
    from game.paga_ai_monitoring import countries
    return jsonify(countries=countries(db.session,request.args.get('q','').strip()))


@paga_bp.get('/monitoring/cele')
def monitoring_goals():
    monitoring_guard()
    from game.paga_ai_monitoring import goals
    status=request.args.get('status','').strip()
    country=request.args.get('country',type=int)
    return jsonify(goals=goals(db.session,country if country and country>0 else None,status if status in ('ACTIVE','SUSPENDED','ABANDONED','ACHIEVED') else None))


# ---------------- PAGA2: profil państw, konfiguracja, historia decyzji, stan państwa ----------------

def paga2_actor():return session.get('username') or 'Wszechmocny WIKI'


@paga_bp.get('/paga2/panstwa')
def paga2_countries():
    check_access()
    from game.paga2.admin import countries_overview
    return jsonify(countries=countries_overview(db.session))


@paga_bp.route('/paga2/panstwo/<int:country_id>',methods=['GET','POST'])
def paga2_country(country_id):
    check_access()
    if country_id>2147483647:abort(404)
    from game.paga2.admin import country_header,profile_data,save_profile,profile_history,AdminError,AdminConflict
    from game.paga2.catalog import ProfileError
    from game.paga2.models import Paga2Profile
    if request.method=='POST':
        try:
            with Session(db.engine) as database,database.begin():profile=save_profile(database,country_id,request.get_json(silent=True),paga2_actor())
        except AdminConflict as error:return jsonify(error=str(error)),409
        except (AdminError,ProfileError) as error:return jsonify(error=str(error)),400
        return jsonify(profile=profile,history=profile_history(db.session,country_id))
    try:header=country_header(db.session,country_id)
    except LookupError:abort(404)
    header['flag']=url_for('static',filename='flags/'+(header['name'] or '').replace(' ','_')+'.jpg')
    return jsonify(country=header,profile=profile_data(db.session.get(Paga2Profile,country_id,populate_existing=True)),history=profile_history(db.session,country_id))


@paga_bp.route('/paga2/konfiguracja',methods=['GET','POST'])
def paga2_control():
    check_access()
    from game.paga2.admin import control_data,save_control,AdminError,AdminConflict
    try:
        if request.method=='POST':
            with Session(db.engine) as database,database.begin():data=save_control(database,request.get_json(silent=True),paga2_actor())
        else:data=control_data(db.session)
    except AdminConflict as error:return jsonify(error=str(error)),409
    except AdminError as error:return jsonify(error=str(error)),400
    return jsonify(control=data)


@paga_bp.get('/paga2/decyzje')
def paga2_decisions():
    check_access()
    from game.paga2.admin import decisions
    country=request.args.get('country',type=int)
    filters={'country':country if country and 0<country<=2147483647 else None,
             'domain':request.args.get('domain','').strip()[:32] or None,'status':request.args.get('status','').strip()[:16] or None,
             'mode':request.args.get('mode','').strip()[:16] or None}
    return jsonify(**decisions(db.session,filters,request.args.get('page',1,type=int) or 1))


@paga_bp.get('/paga2/decyzje/<int:decision_id>')
def paga2_decision(decision_id):
    check_access()
    from game.paga2.admin import decision_detail
    try:return jsonify(decision=decision_detail(db.session,decision_id))
    except LookupError:abort(404)


@paga_bp.get('/paga2/stan/<int:country_id>')
def paga2_state(country_id):
    check_access()
    if country_id>2147483647:abort(404)
    from game.paga2.admin import country_state
    try:return jsonify(state=country_state(db.session,country_id))
    except LookupError:abort(404)
