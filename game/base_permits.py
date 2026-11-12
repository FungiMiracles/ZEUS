"""Bazy wojskowe w krajach sojuszniczych (12 Nov 2026).

Państwo prosi sojusznika (relacja „sojusznicze”) o pozwolenie na budowę bazy w wybranym regionie (propozycja
dyplomatyczna BASE_PERMIT). Gospodarz — gracz albo PAGA2 — akceptuje lub odrzuca. Po zgodzie region jest dostępny
do budowy na tych samych zasadach co własny; utrzymanie bazy za granicą jest dwukrotnie droższe.

Zmiana relacji gospodarza z gościem (decyzja użytkownika):
- relacje nadal sojusznicze — pozwolenie aktywne;
- relacje gorsze od sojuszniczych, ale powyżej neutralnych — bazy zostają, nowych budować nie można (FROZEN);
- relacje neutralne lub gorsze — pozwolenia wygasają, a bazy gościa w regionach gospodarza są likwidowane
  (garnizon wraca do zasobów państwa, miejsce na bazę nie przepada).
"""
from sqlalchemy import select,inspect
from sqlalchemy.orm import lazyload
from extensions import db
from game.models import utc_now

PERMIT_RELATIONS={'sojusznicze'}
ABROAD_UPKEEP=2


class BasePermit(db.Model):
    __tablename__='game_base_permits'
    id=db.Column(db.Integer,primary_key=True)
    host_country_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID',ondelete='RESTRICT'),nullable=False)
    guest_country_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID',ondelete='RESTRICT'),nullable=False)
    region_id=db.Column(db.Integer,nullable=False)
    status=db.Column(db.String(16),nullable=False,default='ACTIVE')   # ACTIVE / FROZEN / REVOKED
    action_id=db.Column(db.Integer)
    created_at=db.Column(db.DateTime,nullable=False,default=utc_now)
    changed_at=db.Column(db.DateTime)
    __table_args__=(db.Index('ix_base_permit_guest','guest_country_id','status'),db.Index('ix_base_permit_host','host_country_id','status'),
                    db.CheckConstraint("status IN ('ACTIVE','FROZEN','REVOKED')",name='ck_base_permit_status'),{'mysql_engine':'InnoDB'})


_READY={}   # zachowane dla zgodności testów


def ready(session):
    return inspect(session.connection()).has_table(BasePermit.__tablename__)


def _normalized(name):
    from services.natural_resources import normalized
    return normalized(name or '')


def permits(session,guest_id,statuses=('ACTIVE',)):
    if not ready(session):return []
    return list(session.scalars(select(BasePermit).where(BasePermit.guest_country_id==guest_id,BasePermit.status.in_(statuses))))


def permitted_region_ids(session,guest_id):
    """Regiony, w których gość może budować nowe bazy (pozwolenie aktywne)."""
    return {p.region_id for p in permits(session,guest_id)}


def own_region_ids(session,country_id):
    from models import Region
    from game.governance import controlled_ids
    return set(session.scalars(select(Region.region_id).where(Region.panstwo_id.in_(controlled_ids(session,country_id) or [country_id]))))


def is_abroad(session,base,own=None):
    own=own if own is not None else own_region_ids(session,base.panstwo_id)
    return base.region_id is not None and base.region_id not in own


def permit_params(session,source,target,params):
    """Walidacja prośby: region musi należeć do gospodarza, nie może mieć już pozwolenia."""
    from models import Region
    from game.diplomacy_service import DiplomacyError
    try:region_id=int((params or {}).get('region_id'))
    except (TypeError,ValueError):raise DiplomacyError('Wybierz region sojusznika.',400)
    region=session.execute(select(Region.region_id,Region.region_nazwa,Region.panstwo_id).where(Region.region_id==region_id)).first()
    from game.governance import controller_id
    if region is None or controller_id(session,region.panstwo_id)!=target:raise DiplomacyError('Region nie należy do wybranego państwa.',400)
    if ready(session) and session.scalar(select(BasePermit.id).where(BasePermit.guest_country_id==source,BasePermit.region_id==region_id,BasePermit.status.in_(['ACTIVE','FROZEN']))):
        raise DiplomacyError('Pozwolenie na bazę w tym regionie już istnieje.')
    return {'region_id':region_id,'region_name':region.region_nazwa}


def permit_valid(session,action):
    from models import Region
    from game.governance import controller_id
    region=session.execute(select(Region.panstwo_id).where(Region.region_id==(action.params or {}).get('region_id'))).first()
    return region is not None and controller_id(session,region.panstwo_id)==action.target_country_id


def grant(session,action,now):
    if not ready(session):return None
    region=action.params['region_id']
    existing=session.scalar(select(BasePermit).where(BasePermit.guest_country_id==action.source_country_id,BasePermit.region_id==region,BasePermit.status!='REVOKED'))
    if existing:existing.status='ACTIVE';existing.changed_at=utc_now();return existing
    permit=BasePermit(host_country_id=action.target_country_id,guest_country_id=action.source_country_id,region_id=region,status='ACTIVE',action_id=action.id)
    session.add(permit);session.flush();return permit


def liquidate_base(session,base):
    """Likwidacja bazy za granicą po zerwaniu sojuszu: garnizon wraca, miejsce na bazę zostaje."""
    from game.military_destruction import detach_base
    from game.military_models import MilitaryExpense
    detach_base(session,base)
    for expense in session.scalars(select(MilitaryExpense).where(MilitaryExpense.base_id==base.id)):expense.base_id=None
    session.delete(base)


def on_relation_change(session,a,b,relation_name):
    """Wywoływane przy każdej zmianie stosunków pary (a, b)."""
    if not ready(session):return
    from game.diplomacy_service import RELATION_ORDER
    name=_normalized(relation_name)
    rank=RELATION_ORDER.index(name) if name in RELATION_ORDER else RELATION_ORDER.index('neutralne')
    rows=list(session.scalars(select(BasePermit).where(BasePermit.status.in_(['ACTIVE','FROZEN']),
        ((BasePermit.host_country_id==a)&(BasePermit.guest_country_id==b))|((BasePermit.host_country_id==b)&(BasePermit.guest_country_id==a))).with_for_update()))
    if not rows:return
    from game.military_models import MilitaryBase
    from game.forum_models import GameNotification
    from game.paga_ai_actor import country_user_id
    def notify(country_id,text):
        user=country_user_id(session,country_id)
        if user is not None:session.add(GameNotification(user_id=user,notification_type='SYSTEM',system_text=text,created_at=utc_now()))
    if name in PERMIT_RELATIONS:status='ACTIVE'
    elif rank>RELATION_ORDER.index('neutralne'):status='FROZEN'
    else:status='REVOKED'
    removed=0
    for permit in rows:
        if permit.status==status:continue
        permit.status=status;permit.changed_at=utc_now()
        if status=='REVOKED':
            for base in session.scalars(select(MilitaryBase).where(MilitaryBase.panstwo_id==permit.guest_country_id,MilitaryBase.region_id==permit.region_id).with_for_update()):
                liquidate_base(session,base);removed+=1
    guest=rows[0].guest_country_id;host=rows[0].host_country_id
    if status=='FROZEN':notify(guest,'Relacje z gospodarzem Twoich baz zagranicznych pogorszyły się. Bazy pozostają, ale nie można budować nowych.')
    elif status=='REVOKED':notify(guest,f'Relacje z gospodarzem spadły do poziomu neutralnego lub niższego. Pozwolenia na bazy wygasły; zlikwidowano baz: {removed}. Garnizony wróciły do zasobów państwa.')
    session.flush()


def ally_regions(session,country_id):
    """Regiony sojuszników do mapy obrony: {region_id: {...}} z informacją o pozwoleniu i oczekującej prośbie."""
    from models import Region,Stosunki,DictStosunkiRelacja
    from game.governance import controller_id
    from game.diplomacy_models import DiplomaticAction
    names=dict(session.execute(select(DictStosunkiRelacja.relacja_id,DictStosunkiRelacja.relacja_nazwa)).all())
    allies=set()
    for row in session.execute(select(Stosunki.PANSTWO_ID,Stosunki.PANSTWO_ID2,Stosunki.relacja_id).where((Stosunki.PANSTWO_ID==country_id)|(Stosunki.PANSTWO_ID2==country_id))):
        if _normalized(names.get(row.relacja_id)) in PERMIT_RELATIONS:allies.add(row.PANSTWO_ID2 if row.PANSTWO_ID==country_id else row.PANSTWO_ID)
    held={p.region_id:p.status for p in permits(session,country_id,('ACTIVE','FROZEN'))}
    pending={(a.params or {}).get('region_id') for a in session.scalars(select(DiplomaticAction).where(DiplomaticAction.source_country_id==country_id,DiplomaticAction.kind=='BASE_PERMIT',DiplomaticAction.status=='PENDING'))}
    result={}
    for r in session.execute(select(Region.region_id,Region.region_nazwa,Region.panstwo_id,Region.region_polozenie_id)):
        owner=controller_id(session,r.panstwo_id)
        if owner in allies or r.region_id in held:
            result[str(r.region_id)]={'name':r.region_nazwa,'countryId':owner,'coastal':r.region_polozenie_id not in (None,1),
                                      'permit':held.get(r.region_id),'pending':r.region_id in pending}
    return result
