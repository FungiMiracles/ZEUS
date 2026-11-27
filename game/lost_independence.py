"""Anulowanie wiszących wniosków państw, które utraciły niepodległość (26 Nov 2026).

Państwo bez niepodległości (game.sovereignty: wiersz SovereigntyLoss) nie może już rozpatrzyć ani zrealizować wniosku.
Dlatego oczekujące wnioski, w których jest stroną — adresatem albo nadawcą — są anulowane:
* propozycje dyplomatyczne (zmiana stosunków, pokój, rozejm, dołączenie do wojny, zgoda na bazę lub kopalnię
  na obcym terytorium) — status EXPIRED;
* zapytania o współfinansowanie dróg — cancelled;
* wnioski o współfinansowanie międzynarodowych linii kolejowych — CANCELLED;
* wnioski o pożyczkę — cancelled.
Druga strona dostaje powiadomienie. Wywoływane przy utracie niepodległości (lose_sovereignty) oraz okresowo
(harmonogram infrastruktury), co obejmuje też wnioski złożone później do państwa, które już niepodległość utraciło.
"""
from sqlalchemy import select, or_
from game.models import utc_now


def lost_ids(session):
    from game.land_war_models import SovereigntyLoss
    return set(session.scalars(select(SovereigntyLoss.panstwo_id)))


def cancel_requests(session, country_ids=None):
    """Anuluje oczekujące wnioski z udziałem państw `country_ids` (domyślnie: wszystkich bez niepodległości).
    Zwraca liczbę anulowanych wniosków według rodzaju."""
    from models import Panstwo
    from game.land_war import notify
    ids = set(lost_ids(session) if country_ids is None else country_ids)
    counts = {'diplomacy': 0, 'roads': 0, 'rail': 0, 'loans': 0}
    if not ids:
        return counts
    names = {}

    def name(country_id):
        if country_id not in names:
            names[country_id] = session.scalar(select(Panstwo.panstwo_nazwa).where(Panstwo.PANSTWO_ID == country_id)) or f'#{country_id}'
        return names[country_id]

    notices = {}   # państwo → [(opis, państwo bez niepodległości)] — jedno zbiorcze powiadomienie na państwo

    def inform(parties, what):
        lost = [p for p in parties if p in ids]
        for party in parties:
            if party is not None and party not in ids:
                notices.setdefault(party, []).append((what, lost[0]))

    from sqlalchemy import inspect
    tables = inspect(session.connection())
    ready = lambda model: tables.has_table(model.__tablename__)   # tabele funkcji wdrażanych migracjami (np. kolej)
    now = utc_now()
    from game.diplomacy_models import DiplomaticAction
    for action in [] if not ready(DiplomaticAction) else session.scalars(select(DiplomaticAction).where(DiplomaticAction.status == 'PENDING', or_(
            DiplomaticAction.source_country_id.in_(ids), DiplomaticAction.target_country_id.in_(ids))).with_for_update()):
        action.status, action.decided_at = 'EXPIRED', now
        counts['diplomacy'] += 1
        inform((action.source_country_id, action.target_country_id),
               f'Propozycję dyplomatyczną ({action.source_country_name} → {action.target_country_name})')
    from game.civic_models import RoadProposal
    for proposal in [] if not ready(RoadProposal) else session.scalars(select(RoadProposal).where(RoadProposal.status == 'pending', or_(
            RoadProposal.initiator_id.in_(ids), RoadProposal.partner_id.in_(ids))).with_for_update()):
        proposal.status, proposal.resolved_at = 'cancelled', now
        counts['roads'] += 1
        inform((proposal.initiator_id, proposal.partner_id), f'Zapytanie o współfinansowanie drogi #{proposal.id}')
    from game.rail_models import RailLine
    for line in [] if not ready(RailLine) else session.scalars(select(RailLine).where(RailLine.status == 'PENDING', or_(
            RailLine.initiator_id.in_(ids), RailLine.partner_id.in_(ids))).with_for_update()):
        line.status, line.resolved_at = 'CANCELLED', now
        counts['rail'] += 1
        inform((line.initiator_id, line.partner_id), f'Wniosek o współfinansowanie linii kolejowej #{line.id}')
    from game.loan_models import StateLoan
    for loan in [] if not ready(StateLoan) else session.scalars(select(StateLoan).where(StateLoan.status == 'pending', or_(
            StateLoan.borrower_id.in_(ids), StateLoan.lender_id.in_(ids))).with_for_update()):
        loan.status, loan.resolved_at = 'cancelled', now
        counts['loans'] += 1
        inform((loan.borrower_id, loan.lender_id), f'Wniosek o pożyczkę #{loan.id} ({loan.amount} ROI)')
    for party, items in notices.items():
        if len(items) == 1:
            what, lost = items[0]
            notify(session, party, f'{what} anulowano: państwo {name(lost)} utraciło niepodległość.')
        else:
            countries = ', '.join(sorted({name(lost) for _, lost in items}))
            notify(session, party, f'Anulowano {len(items)} oczekujących wniosków z udziałem państw, które utraciły niepodległość ({countries}).')
    return counts
