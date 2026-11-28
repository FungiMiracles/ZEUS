"""Ekran wywiadu i raporty dostępne wyłącznie dla zarządzanego państwa."""
import secrets
from game.governance import controller_id
from flask import Blueprint,redirect,url_for,render_template,jsonify,request,session,abort
from sqlalchemy import select
from extensions import db
from game.forum import player
from game.country_summary import country_summary
from game.military import csrf_valid
from game.finance_service import FinanceError,game_now
from game.intelligence_models import IntelligenceAgent,IntelligenceMission
from game.intelligence_service import (operate,complete_missions,intelligence_budget,counter_level,mission_details,
                                      AGENT_COSTS,AGENT_CHANCES,COUNTER_COSTS,COUNTER_PROTECTION,MISSIONS,MISSION_COSTS,mission_days)
from models import Region,Panstwo
from engine.clock import get_time_multiplier

intelligence_bp=Blueprint('game_intelligence',__name__,url_prefix='/game/wywiad-wojskowy')


def state_data(country_id):
    budget,total,available=intelligence_budget(db.session,country_id)
    level=counter_level(db.session,country_id)
    missions=list(db.session.scalars(select(IntelligenceMission).where(IntelligenceMission.panstwo_id==country_id).order_by(IntelligenceMission.id.desc())))
    agents=list(db.session.scalars(select(IntelligenceAgent).where(IntelligenceAgent.panstwo_id==country_id).order_by(IntelligenceAgent.id)))
    names={agent.id:agent.name or f'Agent #{agent.id}' for agent in agents}
    countries=dict(db.session.execute(select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa)).all())
    busy={mission.agent_id:mission for mission in missions if mission.completed_at is None}
    return {'budgetTotal':str(total),'budgetAvailable':str(available),'counterLevel':level,'protection':COUNTER_PROTECTION[level-1],
        'counterCost':COUNTER_COSTS[level] if level<7 else 0,
        'agents':[{'id':agent.id,'name':names[agent.id],'level':agent.level,'chance':AGENT_CHANCES[agent.level-1],'captured':agent.captured_at is not None,'busy':agent.id in busy} for agent in agents],
        'missions':[{'id':mission.id,'agentId':mission.agent_id,'agentName':names.get(mission.agent_id,f'Agent #{mission.agent_id}'),'country':countries.get(mission.target_country_id,'Państwo celu'),'region':mission.region_name,'regionId':str(mission.region_id) if mission.region_id is not None else None,'countryId':mission.target_country_id,'scope':'country' if mission.kind=='warehouses' else 'region','kind':MISSIONS[mission.kind],
                     'startsAt':mission.starts_at.isoformat()+'Z','endsAt':mission.ends_at.isoformat()+'Z',
                     'captured':bool((mission.report or {}).get('captured')),'completed':mission.completed_at is not None,'success':mission.success} for mission in ([m for m in missions if m.completed_at is None]+[m for m in missions if m.completed_at is not None][:100])],
        'resourceReports':resource_reports(country_id,countries),
        'sabotageAgainstUs':sabotage_against(country_id,countries),
        'gameNow':game_now().isoformat()+'Z','timeMultiplier':get_time_multiplier()}


def sabotage_against(country_id,countries,limit=30):
    """28 Nov 2026: działania hybrydowe wymierzone w państwo. Sprawca jest jawny tylko wtedy, gdy kontrwywiad go ustalił
    (poziom ochrony 6–7 w chwili zakończenia misji) albo schwytano agenta."""
    from game.intelligence_service import HYBRID
    rows=db.session.scalars(select(IntelligenceMission).where(IntelligenceMission.target_country_id==country_id,IntelligenceMission.kind.in_(HYBRID),
                            IntelligenceMission.completed_at.is_not(None)).order_by(IntelligenceMission.completed_at.desc(),IntelligenceMission.id.desc()).limit(limit))
    result=[]
    for mission in rows:
        report=mission.report or {}
        if report.get('invalid_target'):continue
        known=bool(report.get('attributed') or report.get('captured'))
        if not known and not report.get('damage'):continue   # nieudana próba bez ustalenia sprawcy pozostaje niewykryta
        result.append({'kind':MISSIONS[mission.kind],'region':mission.region_name,'date':mission.ends_at.strftime('%d.%m.%Y'),'success':bool(mission.success),
                       'captured':bool(report.get('captured')),'culprit':countries.get(mission.panstwo_id,f'Państwo #{mission.panstwo_id}') if known else None})
    return result


def resource_reports(country_id,countries):
    """21 Nov 2026: rozpoznane zasoby regionów — dostępne przez 180 dni Entendy od zakończenia misji."""
    from game.foreign_mining import reports,report_expires
    return [{'missionId':mission.id,'regionId':str(region_id),'region':mission.region_name,'country':countries.get(mission.target_country_id,'Państwo celu'),
             'entries':(mission.report or {}).get('entries',[]),'date':mission.ends_at.strftime('%d.%m.%Y'),'until':report_expires(mission).strftime('%d.%m.%Y')}
            for region_id,mission in sorted(reports(db.session,country_id).items(),key=lambda item:item[1].ends_at,reverse=True)]


@intelligence_bp.get('')
def page():
    user,country=player()
    if user is None:return redirect(url_for('wejscie'))
    session.setdefault('game_csrf_token',secrets.token_urlsafe(32))
    complete_missions(db.session,game_now(),country.PANSTWO_ID)
    config=state_data(country.PANSTWO_ID)
    config.update({'countryId':country.PANSTWO_ID,'csrf':session['game_csrf_token'],
        'changeUrl':url_for('game_intelligence.change'),'stateUrl':url_for('game_intelligence.state'),
        'reportUrl':url_for('game_intelligence.report',mission_id=0),
        'regionsUrl':url_for('static',filename='maps/entenda_regiony.geojson'),
        'regions':{str(id):{'name':name,'countryId':controller_id(db.session,owner)} for id,name,owner in db.session.execute(select(Region.region_id,Region.region_nazwa,Region.panstwo_id))},
        'countries':{str(id):name for id,name in db.session.execute(select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa))},
        'agentIcon':url_for('static',filename='icons/WYWIAD WOJSKOWY.svg'),'agentCosts':AGENT_COSTS,'agentChances':AGENT_CHANCES,'missionCosts':MISSION_COSTS,'missionDays':{key:mission_days(key) for key in MISSIONS},'missionTypes':MISSIONS,
        'initialReport':request.args.get('raport',type=int)})
    response=render_template('game/intelligence.html',game_user=user,game_country=country_summary(country),
        game_home_url=url_for('game_main_page'),game_logout_url=url_for('game_logout'),game_active_page='intelligence',intelligence_config=config)
    db.session.commit();return response


@intelligence_bp.post('/zmien')
def change():
    user,country=player()
    if user is None:return jsonify(error='Zaloguj się ponownie.'),401
    if not csrf_valid():return jsonify(error='Sesja formularza wygasła. Odśwież stronę.'),403
    data=request.get_json(silent=True)
    if not isinstance(data,dict):return jsonify(error='Nieprawidłowe dane formularza.'),400
    try:operate(user.id,data)
    except FinanceError as exc:return jsonify(error=str(exc)),400
    return jsonify(ok=True)


@intelligence_bp.get('/stan')
def state():
    user,country=player()
    if user is None:return jsonify(error='Zaloguj się ponownie.'),401
    complete_missions(db.session,game_now(),country.PANSTWO_ID)
    response=jsonify(state_data(country.PANSTWO_ID));db.session.commit();response.headers['Cache-Control']='no-store';return response


@intelligence_bp.get('/raport/<int:mission_id>')
def report(mission_id):
    user,country=player()
    if user is None:return jsonify(error='Zaloguj się ponownie.'),401
    mission=db.session.scalar(select(IntelligenceMission).where(IntelligenceMission.id==mission_id,IntelligenceMission.panstwo_id==country.PANSTWO_ID))
    if mission is None:abort(404)
    if mission.completed_at is None:return jsonify(error='Misja jeszcze trwa.'),409
    response=jsonify(report=mission_details(mission));response.headers['Cache-Control']='no-store';return response
