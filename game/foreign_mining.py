"""Regional mining concessions. Accepted diplomatic actions retain the host and guest."""
from datetime import timedelta
from sqlalchemy import select, inspect
from models import Region
from game.diplomacy_models import DiplomaticAction
from game.intelligence_models import IntelligenceMission
from game.governance import controller_id
from services.natural_resources import normalized

RELATIONS={'sojusznicze','partnerskiestrategiczne','partnerskie','przyjazne','dobre','neutralne'}
POLLUTION=2


def eligible(session,guest,host):
    if guest is None or host is None or guest==host:return False
    from game.diplomacy_service import dictionaries,pair_state
    relations,states,neutral=dictionaries(session)
    _,relation,state,_=pair_state(session,*sorted((guest,host)),neutral,states['pokoj'])
    return normalized(relations.get(relation) or '') in RELATIONS and state!=states['wojnakinetyczna']


def reports(session,country):
    if not inspect(session.connection()).has_table(IntelligenceMission.__tablename__):return {}
    return {r.region_id:r for r in session.scalars(select(IntelligenceMission).where(IntelligenceMission.panstwo_id==country,IntelligenceMission.kind=='resources',IntelligenceMission.success.is_(True)).order_by(IntelligenceMission.id)) if not (r.report or {}).get('invalid_target')}


def concessions(session,country):
    if not inspect(session.connection()).has_table(DiplomaticAction.__tablename__):return {}
    return {(r.params or {}).get('region_id'):r for r in session.scalars(select(DiplomaticAction).where(DiplomaticAction.source_country_id==country,DiplomaticAction.kind=='MINING_PERMIT',DiplomaticAction.status=='ACCEPTED'))}


def allowed(session,guest,region):
    permit=concessions(session,guest).get(region.region_id)
    return bool(permit and permit.target_country_id==controller_id(session,region.panstwo_id))


def permit_params(session,source,target,params):
    from game.diplomacy_service import DiplomacyError
    try:rid=int((params or {}).get('region_id'))
    except (TypeError,ValueError):raise DiplomacyError('Wybierz region.',400)
    region=session.get(Region,rid)
    if region is None or controller_id(session,region.panstwo_id)!=target:raise DiplomacyError('Region zmienił właściciela.')
    report=reports(session,source).get(rid)
    if report is None or report.target_country_id!=target:raise DiplomacyError('Najpierw pomyślnie przeszpieguj zasoby regionu.')
    if allowed(session,source,region):raise DiplomacyError('Pozwolenie już istnieje.')
    return {'region_id':rid,'region_name':region.region_nazwa}


def valid(session,action):
    region=session.get(Region,(action.params or {}).get('region_id'))
    return region is not None and controller_id(session,region.panstwo_id)==action.target_country_id and eligible(session,action.source_country_id,action.target_country_id)


def map_regions(session,country):
    known=reports(session,country);held=concessions(session,country);result={};relations={}
    pending={a.params.get('region_id') for a in session.scalars(select(DiplomaticAction).where(DiplomaticAction.source_country_id==country,DiplomaticAction.kind=='MINING_PERMIT',DiplomaticAction.status=='PENDING'))} if inspect(session.connection()).has_table(DiplomaticAction.__tablename__) else set()
    for region in session.scalars(select(Region)):
        host=controller_id(session,region.panstwo_id)
        if host==country:continue
        if host not in relations:relations[host]=eligible(session,country,host)
        report=known.get(region.region_id);report=report if report and report.target_country_id==host else None
        permit=held.get(region.region_id)
        result[str(region.region_id)]={'name':region.region_nazwa,'countryId':host,'foreign':True,'permit':bool(permit and permit.target_country_id==host),'canRequest':bool(report and relations[host] and region.region_id not in pending and not permit),'pending':region.region_id in pending,'report':(report.report or {}).get('entries',[]) if report else [],'projects':{},'coastal':False}
    return result


def seize(session,region_id,country,now):
    from game.commerce_models import Mine
    for mine in session.scalars(select(Mine).where(Mine.region_id==region_id,Mine.removed_at.is_(None)).with_for_update()):
        mine.panstwo_id=country
        mine.extracted_at=max(mine.extracted_at,now)


def host_may_remove(session,mine,host,now):
    region=session.get(Region,mine.region_id)
    return region is not None and controller_id(session,region.panstwo_id)==host and mine.panstwo_id!=host and now>=mine.ready_at+timedelta(days=180)
