"""Dyplomacja graczy: mapa, propozycje, zgoda odbiorcy i audyt."""
import unicodedata

from game.governance import controller_id
from flask import Blueprint, abort, jsonify, redirect, render_template, request, url_for, current_app
from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import lazyload

from engine.clock import get_current_entenda_datetime
from extensions import db
from game.country_summary import country_summary
from game.diplomacy_models import DiplomaticAction
from game.diplomacy_service import can_declare_war,is_pact,relation_rank
from game.forum import player, real_date, validate_csrf
from game.forum_models import GameNotification
from game.models import GamePlayerCountry, GameUser, utc_now
from models import AudytStosunki, DictStosunkiRelacja, DictStosunkiStan, Panstwo, Stosunki


diplomacy_bp = Blueprint("game_diplomacy", __name__, url_prefix="/game/dyplomacja")
ACTION_TEXT = {
    "WAR": "wypowiada wojnę Twojemu krajowi",
    "PEACE": "proponuje zawarcie pokoju",
    "CEASEFIRE": "proponuje zawieszenie broni w trwającej wojnie",
    "RELATION": "proponuje zmianę relacji z Twoim krajem",
    "JOIN_WAR": "prosi o dołączenie do wojny",
    "MINING_PERMIT": "prosi o pozwolenie na wydobycie surowców",
    "BASE_PERMIT": "prosi o pozwolenie na budowę bazy wojskowej",
}
PROPOSAL_KINDS = ['MINING_PERMIT','RELATION','PEACE','CEASEFIRE','JOIN_WAR','BASE_PERMIT']


def proposal_label(action, relation_labels):
    params = action.params or {}
    if action.kind == 'RELATION': return relation_labels.get(action.proposed_relation_id, 'Brak danych')
    if action.kind == 'JOIN_WAR': return 'Dołączenie do wojny z państwem ' + (params.get('enemy_name') or '?')
    if action.kind == 'MINING_PERMIT': return 'Wydobycie w regionie ' + (params.get('region_name') or '?') + '. Budowa kosztuje 2×; połowa kosztu trafia do budżetu infrastruktury gospodarza. Zanieczyszczenie pozostaje w regionie. Gospodarz może zlikwidować kopalnię po 180 dniach od ukończenia budowy.'
    if action.kind == 'BASE_PERMIT': return 'Pozwolenie na bazę w regionie ' + (params.get('region_name') or '?')
    if action.kind == 'CEASEFIRE' and params.get('days'): return f"Zawieszenie broni na {params['days']} dni Entendy"
    return {'PEACE':'Zawarcie pokoju','CEASEFIRE':'Zawieszenie broni'}[action.kind]
RELATION_COLORS = {
    "sojusznicze": "#166534", "partnerskiestrategiczne": "#15803d",
    "partnerskie": "#22c55e", "przyjazne": "#86efac", "dobre": "#bbf7d0",
    "neutralne": "#cbd5e1", "chlodne": "#fef08a", "zle": "#fdba74",
    "napiete": "#f97316", "wrogie": "#ef4444", "egzystencjalniewrogie": "#991b1b",
}


def key(label):
    label = unicodedata.normalize("NFKD", label.lower().replace("ł", "l"))
    return "".join(char for char in label if char.isascii() and char.isalnum())


def dictionaries():
    relations = db.session.scalars(select(DictStosunkiRelacja).order_by(DictStosunkiRelacja.relacja_id)).all()
    states = db.session.scalars(select(DictStosunkiStan)).all()
    by_state = {key(item.stan_nazwa): item.stan_id for item in states}
    by_relation = {key(item.relacja_nazwa): item.relacja_id for item in relations}
    required = [by_state.get(name) for name in ["pokoj", "wojnakinetyczna", "zawieszeniebroni"]]
    if not all(required) or "neutralne" not in by_relation:
        abort(409, description="Brak wymaganych pozycji w słownikach relacji lub stanów dyplomatycznych.")
    return relations, states, by_state, by_relation["neutralne"]


def pair_filter(model, a, b):
    if model is Stosunki:
        return (model.PANSTWO_ID == a) & (model.PANSTWO_ID2 == b)
    return (model.panstwo_id == a) & (model.panstwo_id2 == b)


def pair_state(a, b, neutral, peace):
    row = db.session.scalar(select(Stosunki).where(pair_filter(Stosunki, a, b))
                            .options(lazyload("*")).execution_options(populate_existing=True).with_for_update())
    revision = db.session.scalar(select(AudytStosunki.id).where(pair_filter(AudytStosunki, a, b))
                                 .order_by(AudytStosunki.id.desc()).limit(1).with_for_update()) or 0
    return row, row.relacja_id if row and row.relacja_id is not None else neutral, row.stan_id if row and row.stan_id is not None else peace, revision


def lock_pair(a, b):
    # Kanoniczna kolejność blokad zabezpiecza także parę bez wpisu w stosunki.
    db.session.execute(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID.in_([a, b]))
                       .order_by(Panstwo.PANSTWO_ID).with_for_update()).all()


def apply_change(row,a,b,relation,state):
    from game.diplomacy_service import apply_change as shared_change
    return shared_change(db.session,row,a,b,relation,state,get_current_entenda_datetime())


def fail(description, code=409):
    db.session.rollback()
    return jsonify(error=description), code


@diplomacy_bp.get("")
def page():
    user, country = player()
    if user is None:
        return redirect(url_for("wejscie"))
    relations, states, state_ids, neutral = dictionaries()
    countries = db.session.execute(select(Panstwo.PANSTWO_ID, Panstwo.panstwo_nazwa,Panstwo.status)).all()
    owners = dict(db.session.execute(select(GamePlayerCountry.panstwo_id, GameUser.id)
                 .join(GameUser, GameUser.id == GamePlayerCountry.user_id).where(GameUser.is_active.is_(True))).all())
    rows = db.session.scalars(select(Stosunki).where(or_(
        Stosunki.PANSTWO_ID == country.PANSTWO_ID, Stosunki.PANSTWO_ID2 == country.PANSTWO_ID,
    )).options(lazyload("*"))).all()
    by_country = {row.PANSTWO_ID2 if row.PANSTWO_ID == country.PANSTWO_ID else row.PANSTWO_ID: row for row in rows}
    relation_labels = {item.relacja_id: item.relacja_nazwa for item in relations}
    state_labels = {item.stan_id: item.stan_nazwa for item in states}
    colors = {item.relacja_id: RELATION_COLORS.get(key(item.relacja_nazwa), "#a5b4fc") for item in relations}
    from game.paga import approved_country_ids
    paga_ids=approved_country_ids(db.session) if current_app.config.get("PAGA_ENABLED") else set()
    if current_app.config.get("PAGA_ENABLED"):
        from game.diplomacy_service import npc_eligible
        owners=set(owners)|{id for id in paga_ids if npc_eligible(db.session,id)}
    data = {}
    from game.diplomacy_service import joinable_wars, JOIN_RELATIONS, peace_grace_map, PEACE_GRACE_DAYS, ceasefire_map, CEASEFIRE_MIN_DAYS, CEASEFIRE_MAX_DAYS
    now = get_current_entenda_datetime()
    grace = peace_grace_map(db.session, country.PANSTWO_ID, now)
    ceasefires = ceasefire_map(db.session, country.PANSTWO_ID, now)   # 17 Nov 2026: zawieszenie broni na określony czas
    from services.natural_resources import normalized as normalize_relation
    names = {id: name for id, name, status in countries}
    active_ids={id for id,name,status in countries if status=='aktywne'}
    for country_id, name,status in countries:
        owner_id = controller_id(db.session, country_id)
        row = by_country.get(owner_id)
        relation = row.relacja_id if row and row.relacja_id is not None else neutral
        state = row.stan_id if row and row.stan_id is not None else state_ids["pokoj"]
        own = owner_id == country.PANSTWO_ID
        war_allowed=can_declare_war(relation_labels.get(relation),state,state_ids['wojnakinetyczna'])
        grace_until=grace.get(owner_id)
        if grace_until is not None:war_allowed=False   # 16 Nov 2026: karencja po zawarciu pokoju
        ceasefire_until=ceasefires.get(owner_id)
        if ceasefire_until is not None:war_allowed=False
        pact=is_pact(relation_labels.get(relation))
        can_worsen=any(relation_rank(label)<relation_rank(relation_labels.get(relation)) for label in relation_labels.values())
        join_wars = []
        if not own and pact and owner_id in owners and owner_id in active_ids and normalize_relation(relation_labels.get(relation)) in JOIN_RELATIONS:
            join_wars = [{"id": enemy, "name": names.get(enemy, str(enemy))} for enemy in joinable_wars(db.session, country.PANSTWO_ID, owner_id, now)]
        data[str(country_id)] = {
            "name": name, "own": own, "relationId": relation,
            "pagaConfigured":country_id in paga_ids,
            "flag": url_for("static", filename="flags/" + (name or "").replace(" ", "_") + ".jpg"),
            "relation": relation_labels.get(relation, "Brak danych"),
            "state": state_labels.get(state, "Brak danych"),
            "color": "#2563eb" if own else colors.get(relation, "#a5b4fc"),
            "war": state == state_ids["wojnakinetyczna"],
            "canAct": not own and owner_id in active_ids and (owner_id in owners or war_allowed or can_worsen),
            "canPropose":owner_id in owners,
            "canWar": war_allowed,
            "pact": pact, "canWorsen": can_worsen,
            "canNegotiate": state == state_ids["wojnakinetyczna"],
            "joinWars": join_wars,
            "peaceGraceUntil": grace_until.strftime('%d.%m.%Y %H:%M') if grace_until is not None else None,
            "ceasefireUntil": ceasefire_until.strftime('%d.%m.%Y %H:%M') if ceasefire_until is not None else None,
        }
    # 16 Nov 2026: „Trwające konflikty” — wszystkie wojny kinetyczne na świecie (pary państw), nie tylko wojny gracza.
    known={id for id,name,status in countries}
    world_wars=len({tuple(sorted(pair)) for pair in db.session.execute(select(Stosunki.PANSTWO_ID,Stosunki.PANSTWO_ID2).where(
        Stosunki.stan_id==state_ids["wojnakinetyczna"])).all() if pair[0]!=pair[1] and pair[0] in known and pair[1] in known})
    from game.paga_ai_actor import current_actor
    recipient_condition=DiplomaticAction.recipient_user_id==user.id
    if current_actor() is not None:recipient_condition=or_(recipient_condition,DiplomaticAction.recipient_user_id.is_(None))
    pending=list(db.session.scalars(select(DiplomaticAction).where(
        DiplomaticAction.kind.in_(PROPOSAL_KINDS),DiplomaticAction.status=='PENDING',
        or_((DiplomaticAction.sender_user_id==user.id)&(DiplomaticAction.source_country_id==country.PANSTWO_ID),
            recipient_condition&(DiplomaticAction.target_country_id==country.PANSTWO_ID))
    ).order_by(DiplomaticAction.id.desc())))
    proposals=[{'id':action.id,'outgoing':action.source_country_id==country.PANSTWO_ID,
                'country':action.target_country_name if action.source_country_id==country.PANSTWO_ID else action.source_country_name,
                'kind':action.kind,
                'relation':proposal_label(action,relation_labels),
                'decisionUrl':url_for('game_diplomacy.decide',action_id=action.id)} for action in pending]
    return render_template(
        "game/dyplomacja.html", game_user=user, game_country=country_summary(country),
        game_home_url=url_for("game_main_page"), game_logout_url=url_for("game_logout"),
        game_active_page="diplomacy", relations=relations, diplomacy_proposals=proposals, world_wars=world_wars,
        legend=[{"name": item.relacja_nazwa, "color": colors[item.relacja_id]} for item in relations],
        diplomacy_map={"peaceGraceDays": PEACE_GRACE_DAYS, "ceasefireDays": [CEASEFIRE_MIN_DAYS, CEASEFIRE_MAX_DAYS], "relationRanks": {id:relation_rank(label) for id,label in relation_labels.items()}, "pactRelations": [id for id,label in relation_labels.items() if is_pact(label)], "countries": data, "countriesUrl": url_for('region_sovereignty.country_boundaries'),
                       "actionUrl": url_for("game_diplomacy.create_action")},
    )


@diplomacy_bp.post("/akcje")
def create_action():
    user,country=player()
    if user is None:return jsonify(error="Zaloguj się ponownie."),401
    validate_csrf()
    from game.diplomacy_service import create_action as create_shared,DiplomacyError
    target=controller_id(db.session,request.form.get('target_id',type=int))
    if not target:return fail('Nieprawidłowa akcja lub państwo.',400)
    try:
        params={'enemy_id':request.form.get('enemy_id',type=int)} if request.form.get('kind')=='JOIN_WAR' else {'region_id':request.form.get('region_id',type=int)} if request.form.get('kind') in ('BASE_PERMIT','MINING_PERMIT') else {'days':request.form.get('days',type=int)} if request.form.get('kind')=='CEASEFIRE' else None
        action=create_shared(db.session,country.PANSTWO_ID,target,request.form.get('kind'),request.form.get('relation_id',type=int),get_current_entenda_datetime(),sender_user_id=user.id,params=params)
        db.session.commit()
        return jsonify(message='Wypowiedziano wojnę.' if action.kind=='WAR' else 'Jednostronnie pogorszono relacje. Druga strona otrzyma powiadomienie.' if action.status=='APPLIED' else 'Wysłano propozycję dyplomatyczną.'),201
    except DiplomacyError as error:return fail(str(error),error.status)
    except SQLAlchemyError:return fail('Nie udało się zapisać akcji. Spróbuj ponownie.',503)


@diplomacy_bp.post('/propozycje/<int:action_id>/decyzja')
def decide(action_id):
    user,country=player()
    if user is None:return jsonify(error='Zaloguj się ponownie.'),401
    validate_csrf()
    decision=request.form.get('decision')
    if decision not in ('accept','reject'):return fail('Nieprawidłowa decyzja.',400)
    from game.diplomacy_service import decide_action,DiplomacyError
    try:
        status=decide_action(db.session,action_id,country.PANSTWO_ID,decision=='accept',get_current_entenda_datetime(),user_id=user.id)
        db.session.commit()
        if status=='EXPIRED':return jsonify(error='Propozycja jest nieaktualna. Stosunki lub przypisanie graczy uległy zmianie.'),409
        return jsonify(message='Zaakceptowano propozycję.' if decision=='accept' else 'Odrzucono propozycję.')
    except DiplomacyError as error:return fail(str(error),error.status)
    except SQLAlchemyError:return fail('Nie udało się zapisać decyzji. Spróbuj ponownie.',503)


def notification_text(action,user_id):
    if action.sender_user_id==user_id:
        proposal={'RELATION':'zmiany relacji','PEACE':'zawarcia pokoju','CEASEFIRE':'zawieszenia broni',
                  'JOIN_WAR':'dołączenia do wojny z państwem '+str((action.params or {}).get('enemy_name') or ''),
                  'BASE_PERMIT':'pozwolenia na bazę w regionie '+str((action.params or {}).get('region_name') or '')}.get(action.kind,'działania dyplomatycznego')
        if action.status in ('ACCEPTED','REJECTED'):
            decision='zaakceptowało' if action.status=='ACCEPTED' else 'odrzuciło'
            return f'Państwo {action.target_country_name} {decision} Twoją propozycję {proposal}.'
        if action.status=='EXPIRED':return f'Twoja propozycja {proposal} skierowana do państwa {action.target_country_name} jest nieaktualna.'
        if action.status=='PENDING':return f'Twoja propozycja {proposal} skierowana do państwa {action.target_country_name} oczekuje na odpowiedź.'
    if action.kind=='JOIN_WAR':return f"{action.source_country_name} prosi o dołączenie do wojny z państwem {(action.params or {}).get('enemy_name') or '?'}. Zgoda oznacza natychmiastowy stan wojny z tym państwem."
    if action.kind=='MINING_PERMIT':return f"{action.source_country_name} prosi o pozwolenie na wydobycie w regionie {(action.params or {}).get('region_name')}. Połowa podwójnego kosztu budowy trafi do Twojego budżetu infrastruktury; zanieczyszczenie pozostanie w regionie. Likwidacja możliwa po 180 dniach od ukończenia budowy."
    if action.kind=='BASE_PERMIT':return f"{action.source_country_name} prosi o pozwolenie na budowę bazy wojskowej w regionie {(action.params or {}).get('region_name') or '?'}."
    if action.kind=='CEASEFIRE' and (action.params or {}).get('days'):
        return f"{action.source_country_name} {ACTION_TEXT['CEASEFIRE']} na {action.params['days']} dni Entendy. Do końca tego okresu żadna ze stron nie będzie mogła wypowiedzieć drugiej wojny."
    return action.source_country_name+' '+('jednostronnie pogarsza relacje' if action.kind=='RELATION' and action.status=='APPLIED' else ACTION_TEXT[action.kind])+'.'


def action_details(action, user, country):
    relation = db.session.get(DictStosunkiRelacja, action.proposed_relation_id) if action.proposed_relation_id else None
    # 16 Nov 2026: w oknie propozycji pokazujemy zmianę „z → na” oraz flagę państwa proponującego.
    previous = db.session.get(DictStosunkiRelacja, action.expected_relation_id) if action.kind == 'RELATION' and action.expected_relation_id else None
    return {
        "relation_from": previous.relacja_nazwa if previous else None,
        "source_country": action.source_country_name,
        "source_flag": url_for("static", filename="flags/" + (action.source_country_name or "").replace(" ", "_") + ".jpg"),
        "title": "Dyplomacja: " + (action.target_country_name if action.sender_user_id==user.id else action.source_country_name),
        "text": notification_text(action,user.id),
        "relation": relation.relacja_nazwa if relation else None,
        "status": {"PENDING": "Oczekuje na decyzję", "APPLIED": "Relacja została zmieniona jednostronnie" if action.kind=='RELATION' else "Wojna została wypowiedziana",
                   "ACCEPTED": "Propozycja zaakceptowana", "REJECTED": "Propozycja odrzucona",
                   "EXPIRED": "Propozycja nieaktualna"}[action.status],
        "received_at": real_date(action.created_at),
        "can_decide": action.status == "PENDING" and action.recipient_user_id == user.id and action.target_country_id == country.PANSTWO_ID,
        "decision_url": url_for("game_diplomacy.decide", action_id=action.id),
    }


@diplomacy_bp.get('/wiadomosci-swiatowe')
def world_news():
    from game.diplomacy_news import enabled,feed
    user,country=player()
    if user is None:return jsonify(error='Zaloguj się ponownie.'),401
    if not enabled():abort(404)
    return feed(user,country)


@diplomacy_bp.post('/wiadomosci-swiatowe/odczytaj')
def read_world_news():
    from game.diplomacy_news import enabled,NewsNotice,NewsEvent,unread_count
    from sqlalchemy import update
    user,country=player()
    if user is None:return jsonify(error='Zaloguj się ponownie.'),401
    if not enabled():abort(404)
    validate_csrf()
    user_id,country_id=user.id,country.PANSTWO_ID
    allowed=select(NewsEvent.id).where(NewsEvent.a!=country_id,NewsEvent.b!=country_id)
    if request.form.get('all')=='1':
        # 16 Nov 2026: „Oznacz wszystkie jako przeczytane” w panelu powiadomień modułu dyplomatycznego.
        db.session.execute(update(NewsNotice).where(NewsNotice.user_id==user.id,NewsNotice.event_id.in_(allowed),NewsNotice.read_at.is_(None)).values(read_at=utc_now()))
    else:
        ids=request.form.getlist('ids')
        if not ids or len(ids)>20 or any(not value.isdecimal() for value in ids):return jsonify(error='Nieprawidłowa lista powiadomień.'),400
        db.session.execute(update(NewsNotice).where(NewsNotice.user_id==user.id,NewsNotice.event_id.in_([int(value) for value in ids]),NewsNotice.event_id.in_(allowed),NewsNotice.read_at.is_(None)).values(read_at=utc_now()))
    db.session.commit()
    return jsonify(unread_count=unread_count(user_id,country_id))
