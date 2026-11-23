"""Wyzwalanie regionów spod aneksji i wskrzeszanie państw (UAT, 23 Nov 2026).

Zasady zatwierdzone przez administratora:
* Region anektowany wcześniej przez państwo X z państwa Y gracz zajmuje zwykłą inwazją i okupacją (game.land_war).
  Po czasie potrzebnym do aneksji (ANNEX_DAYS) okupant wybiera: anektuje region sam (land_war.annex_region) albo
  przywraca go państwu Y („dawny właściciel” z game.region_history).
* Y nadal istnieje → region wraca do Y. Y utraciło suwerenność → Y zostaje wskrzeszone w tym regionie:
  (i) stolica w największym mieście regionu, (ii) ludność i powierzchnia z regionu, (iii) ta sama nazwa i flaga
  (to samo państwo w bazie), (iv) PKB = PKB per capita X × ludność regionu (odejmowane X).
* Wskrzeszonym państwem rządzi jego dawny gracz (blokada utraty suwerenności znika); państwo bez gracza przejmuje PAGA2.
* Wskrzeszone państwo zaczyna puste: bez armii i środków (niewydane środki ostatniego budżetu zerowane korektą),
  w sojuszu z wyzwolicielem i w wojnie z X. Bazy regionu przechodzą do Y puste, armie wyzwoliciela wracają do baz.
* Kolejne dawne regiony Y wyzwala się tak samo (wybór: aneksja albo przywrócenie Y).
* Regionu ze stolicą X nie można przywrócić (jego aneksja kończy suwerenność X) — tylko anektować.
"""
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4
from sqlalchemy import select, func
from sqlalchemy.orm import Session, lazyload
from extensions import db
from models import Panstwo, Miasto, Region, Wojsko
from game.finance_service import FinanceError, game_now
from game.land_war_models import Occupation, SovereigntyLoss
from game.military_models import MilitaryBase
from game import land_war
from game.models import utc_now

CAPITAL = 1
ACTOR = 'Wskrzeszenie państwa'


def restore_candidate(session, row, own):
    """{countryId, name, resurrect} — państwo, któremu okupant (`own`) może przywrócić okupowany region; None — brak."""
    if row is None or row.kind != 'region':
        return None
    from game.region_history import former_owner
    candidate = former_owner(session, row.region_id, row.owner_id)
    if candidate is None or candidate in (own, row.owner_id):
        return None
    country = session.execute(select(Panstwo.panstwo_nazwa, Panstwo.status).where(Panstwo.PANSTWO_ID == candidate)).first()
    if country is None or country.status != 'aktywne':
        return None
    # Region ze stolicą obecnego właściciela: jego aneksja kończy suwerenność właściciela — tylko aneksja.
    if session.scalar(select(Miasto.miasto_id).where(Miasto.region_id == row.region_id, Miasto.panstwo_id == row.owner_id,
                                                     Miasto.miasto_typ_id == CAPITAL).limit(1)) is not None:
        return None
    return {'countryId': candidate, 'name': country.panstwo_nazwa, 'resurrect': session.get(SovereigntyLoss, candidate) is not None}


def restore_region(user_id, data):
    """Okupant przywraca okupowany region dawnemu właścicielowi (albo go wskrzesza) — zamiast aneksji."""
    from game.military_service import reconcile_maintenance
    with Session(db.engine) as session, session.begin():
        country = land_war._player_country(session, user_id)
        own = country.PANSTWO_ID
        row = session.scalar(select(Occupation).where(Occupation.id == land_war.natural(data.get('occupation_id'), 'Okupacja', 1),
                                                      Occupation.kind == 'region', Occupation.occupier_id == own,
                                                      Occupation.status == 'ACTIVE').with_for_update())
        if row is None:
            raise FinanceError('Ten region nie jest okupowany przez nasze państwo.')
        now = game_now()
        if now < row.started_at + timedelta(days=land_war.ANNEX_DAYS):
            raise FinanceError(f'Decyzja o regionie będzie możliwa po {land_war.ANNEX_DAYS} dniach Entendy okupacji '
                               f'({(row.started_at + timedelta(days=land_war.ANNEX_DAYS)):%Y-%m-%d %H:%M}).')
        option = restore_candidate(session, row, own)
        if option is None:
            raise FinanceError('Tego regionu nie można przywrócić innemu państwu — można go tylko anektować.')
        expected = data.get('country_id')
        if expected is not None and expected != option['countryId']:
            raise FinanceError('Dawny właściciel regionu zmienił się. Odśwież stronę.')
        holder, target = row.owner_id, option['countryId']
        land_war.lock_countries(session, own, holder, target)
        if not land_war.held_all(session, row.region_id, own, holder):
            raise FinanceError('Przywrócenie regionu wymaga kontroli nad wszystkimi bazami i miastami regionu — przeciwnik odbił część z nich.')
        resurrect = session.get(SovereigntyLoss, target) is not None
        name = _transfer(session, row, own, holder, target, now, resurrect)
        if resurrect:
            _resurrect(session, target, row.region_id, holder, own, now)
        names = land_war.names(session, own, holder, target)
        if resurrect:
            land_war.notify(session, own, f'Wskrzesiliśmy państwo {names.get(target)} w regionie {name}. Jest naszym sojusznikiem i prowadzi wojnę z {names.get(holder)}.')
            land_war.notify(session, holder, f'Państwo {names.get(own)} wyzwoliło region {name} i przywróciło niepodległość państwa {names.get(target)}.')
            land_war.notify(session, target, f'Państwo {names.get(own)} wyzwoliło region {name} spod okupacji {names.get(holder)} i przywróciło nam niepodległość. '
                                             f'Stolica powstała w największym mieście regionu; zaczynamy bez armii i środków w skarbcu.')
        else:
            land_war.notify(session, own, f'Przywróciliśmy region {name} państwu {names.get(target)}.')
            land_war.notify(session, holder, f'Państwo {names.get(own)} wyzwoliło region {name} i przywróciło go państwu {names.get(target)}.')
            land_war.notify(session, target, f'Państwo {names.get(own)} wyzwoliło region {name} spod okupacji {names.get(holder)} i przywróciło go nam.')
        for country_id in (own, holder, target):
            reconcile_maintenance(session, country_id)
        return {'region_id': row.region_id, 'country_id': target, 'resurrected': resurrect}


def _transfer(session, row, own, holder, target, now, resurrect):
    """Region i jego miasta przechodzą do `target`; bazy regionu — puste; armie okupanta (`own`) wracają do baz;
    udział w PKB (PKB per capita posiadacza × ludność regionu) przechodzi od posiadacza do `target`."""
    from game.military_service import BASES, RESOURCES
    from game.foreign_mining import seize
    from game.region_history import record
    gdp = land_war.annexed_gdp(session, holder, row.region_id)
    region = session.scalar(select(Region).options(lazyload('*')).where(Region.region_id == row.region_id).with_for_update())
    seize(session, row.region_id, target, now)
    region.panstwo_id = target
    for city in session.scalars(select(Miasto).options(lazyload('*')).where(Miasto.region_id == row.region_id).with_for_update()):
        city.panstwo_id = target
    session.flush()
    old_army = session.scalar(select(Wojsko).where(Wojsko.panstwo_id == holder).with_for_update())
    new_army = session.scalar(select(Wojsko).where(Wojsko.panstwo_id == target).with_for_update())
    for occupation in session.scalars(select(Occupation).where(Occupation.region_id == row.region_id, Occupation.status == 'ACTIVE',
                                                               Occupation.occupier_id == own, Occupation.kind.in_(['base', 'city']))):
        occupation.status, occupation.ended_at = 'ENDED', now
        object_id = occupation.base_id if occupation.kind == 'base' else occupation.city_id
        for army in land_war._occupiers(session, occupation.kind, object_id):
            land_war._return_home(session, army)
        if occupation.kind == 'base' and occupation.base_id:
            base = session.get(MilitaryBase, occupation.base_id, with_for_update=True)
            if base is None or base.panstwo_id == target:
                continue
            _, base_field, soldier_field = BASES[base.kind]
            # Poprzedni posiadacz traci bazę i sprzęt, który w niej został; baza przechodzi do `target` pusta.
            if old_army is not None and base.panstwo_id == holder:
                for resource, count in (base.garrison or {}).items():
                    field = soldier_field if resource == 'soldiers' else RESOURCES.get(resource, (None, None))[1]
                    if count and field:
                        setattr(old_army, field, max(0, (getattr(old_army, field) or 0) - count))
                if base_field:
                    setattr(old_army, base_field, max(0, (getattr(old_army, base_field) or 0) - 1))
            if new_army is not None and base_field:
                setattr(new_army, base_field, (getattr(new_army, base_field) or 0) + 1)
            base.panstwo_id = target
            base.garrison = {}
    row.status, row.ended_at = 'ENDED', now
    session.flush()
    record(session, row.region_id, holder, target, 'RESTORE', now, occupation_id=row.id, actor=own, details={'resurrected': resurrect})
    land_war.transfer_gdp(session, holder, target, gdp, now)
    land_war.recount_country(session, holder)
    land_war.recount_country(session, target)
    return region.region_nazwa


def _resurrect(session, country_id, region_id, holder, liberator, now):
    loss = session.get(SovereigntyLoss, country_id)
    archived = {'annexed_by': loss.annexed_by, 'capital_region_id': loss.capital_region_id, 'lost_at': loss.lost_at.isoformat(),
                'occupation_id': loss.occupation_id}
    session.delete(loss)
    session.flush()
    # (i) stolica w największym mieście regionu; pozostałe stolice państwa (gdyby jakaś została) stają się stolicami regionów
    largest = session.scalar(select(Miasto).options(lazyload('*')).where(Miasto.region_id == region_id, Miasto.czy_na_mapie == 'TAK')
                             .order_by(Miasto.miasto_populacja.desc(), Miasto.miasto_id).limit(1).with_for_update())
    if largest is None:
        largest = session.scalar(select(Miasto).options(lazyload('*')).where(Miasto.region_id == region_id)
                                 .order_by(Miasto.miasto_populacja.desc(), Miasto.miasto_id).limit(1).with_for_update())
    if largest is not None:
        from game.sovereignty import demote_capitals
        demote_capitals(session, country_id)
        largest.miasto_typ_id = CAPITAL
    # Pusty start: zasoby wojska wyzerowano przy utracie suwerenności (przeszły do anektującego) — zostają tylko bazy regionu
    # dopisane przy przekazaniu; skarbiec bez środków.
    _empty_treasury(session, country_id)
    _diplomacy(session, country_id, liberator, holder, now)
    _government(session, country_id)
    # Archiwum utraty suwerenności zostaje w historii przynależności (wiersz RESTORE zapisany przy przekazaniu regionu).
    from game.region_history import update_details
    update_details(session, region_id, {'resurrected': True, 'sovereignty_restored': archived})


def _empty_treasury(session, country_id):
    """Niewydane środki ostatniego budżetu i rezerwa skarbca → 0, korektami skarbca (łańcuch rozliczeń budżetu pozostaje spójny)."""
    from game.finance_models import StateBudget, StateFinancialAccount
    from game.civic_models import TreasuryAdjustment
    from game.budget_transfers import sector_balances
    account = session.scalar(select(StateFinancialAccount).where(StateFinancialAccount.panstwo_id == country_id).with_for_update())
    if account is None:
        return
    budget = session.get(StateBudget, account.last_budget_id) if account.last_budget_id else None
    reason = 'Wskrzeszenie państwa: start bez środków w skarbcu'
    add = lambda category, amount: session.add(TreasuryAdjustment(panstwo_id=country_id, budget_id=budget.id if budget else None, category=category,
                                                                   amount=-amount, admin_actor=ACTOR, reason=reason, request_id=str(uuid4())))
    if budget is not None:
        for code, item in sector_balances(session, budget).items():
            remaining = Decimal(item['remaining'] or 0).quantize(Decimal('0.01'))
            if code != 'reserve' and remaining > 0:
                add(code, remaining)
    if account.reserve_balance and account.reserve_balance > 0:
        add('reserve', account.reserve_balance)
        account.reserve_balance = Decimal(0)
        account.updated_at = utc_now()
    session.flush()


def _diplomacy(session, country_id, liberator, holder, now):
    """Sojusz z wyzwolicielem (pokój) i wojna z państwem, które anektowało region."""
    from game.diplomacy_service import dictionaries, pair_state, apply_change
    from services.natural_resources import normalized
    relations, states, neutral = dictionaries(session)
    by_name = {normalized(name): id for id, name in relations.items()}
    for other, relation, state in ((liberator, 'sojusznicze', 'pokoj'), (holder, 'wrogie', 'wojnakinetyczna')):
        if other is None or other == country_id:
            continue
        a, b = sorted((country_id, other))
        row, current, _, _ = pair_state(session, a, b, neutral, states['pokoj'])
        apply_change(session, row, a, b, by_name.get(relation, current), states[state], now)


def _government(session, country_id):
    """Dawny gracz odzyskuje państwo (blokada znika razem z SovereigntyLoss); państwo bez gracza przejmuje PAGA2."""
    from game.models import GamePlayerCountry
    if session.scalar(select(GamePlayerCountry.id).where(GamePlayerCountry.panstwo_id == country_id)) is not None:
        return 'player'
    from game.paga2.models import Paga2Profile, Paga2ProfileRevision, table_ready
    if not table_ready(session, Paga2Profile):
        return None
    from game.paga2.catalog import default_profile
    at = utc_now().replace(tzinfo=None)
    profile = session.get(Paga2Profile, country_id, with_for_update=True)
    if profile is None:
        profile = Paga2Profile(panstwo_id=country_id, categories=['economic'], priorities=['financial_stability'], traits=default_profile(),
                               autonomy_enabled=True, source='admin', revision=1, updated_at=at, actor=ACTOR)
        session.add(profile)
    elif profile.autonomy_enabled:
        return 'paga2'
    else:
        profile.autonomy_enabled = True
        profile.revision += 1
        profile.updated_at = at
        profile.actor = ACTOR
    session.add(Paga2ProfileRevision(panstwo_id=country_id, revision=profile.revision, actor=ACTOR, created_at=at,
                                     configuration={'categories': profile.categories, 'priorities': profile.priorities,
                                                    'traits': profile.traits, 'autonomyEnabled': True, 'resurrected': True}))
    session.flush()
    return 'paga2'
