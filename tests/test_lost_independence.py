"""26 Nov 2026: wiszące wnioski z udziałem państwa, które utraciło niepodległość, są anulowane (game.lost_independence),
a państwa PAGA nie wysyłają wiadomości prywatnych (game.communication)."""
from datetime import datetime
from decimal import Decimal
from uuid import uuid4
from sqlalchemy import select
from game_features_support import FeatureTestCase
from extensions import db
from game.diplomacy_models import DiplomaticAction
from game.civic_models import RoadProposal
from game.loan_models import StateLoan
from game.forum_models import GameNotification
from game.land_war_models import SovereigntyLoss
from game.lost_independence import cancel_requests

NOW = datetime(2026, 11, 26, 12, 0)


class CancelRequestsTests(FeatureTestCase):
    def setUp(self):
        super().setUp()
        SovereigntyLoss.__table__.create(db.engine, checkfirst=True)

    def proposal(self, source, target, kind='RELATION', status='PENDING'):
        row = DiplomaticAction(sender_user_id=source, recipient_user_id=target, source_country_id=source, target_country_id=target,
                               source_country_name=f'Państwo {source}', target_country_name=f'Państwo {target}', kind=kind, status=status,
                               proposed_relation_id=None, expected_relation_id=1, expected_state_id=1, expected_audit_id=0)
        db.session.add(row); db.session.commit(); return row.id

    def road(self, initiator, partner):
        row = RoadProposal(initiator_id=initiator, partner_id=partner, kind='national', path=[[0, 0], [1, 1]], shares={}, total_cost=Decimal(1),
                           status='pending', request_id=str(uuid4()))
        db.session.add(row); db.session.commit(); return row.id

    def loan(self, borrower, lender):
        row = StateLoan(borrower_id=borrower, lender_id=lender, requested_by=borrower, amount=Decimal(100), status='pending', request_id=str(uuid4()))
        db.session.add(row); db.session.commit(); return row.id

    def lose(self, country, annexer=1):
        db.session.add(SovereigntyLoss(panstwo_id=country, annexed_by=annexer, capital_region_id=1, occupation_id=None, transferred={}, lost_at=NOW))
        db.session.commit()

    def test_pending_requests_of_lost_country_are_cancelled_and_others_kept(self):
        to_lost = self.proposal(1, 2)                 # zapytanie do państwa, które straci niepodległość
        from_lost = self.proposal(2, 3, 'JOIN_WAR')   # i od niego
        permit = self.proposal(4, 2, 'BASE_PERMIT')   # budowa infrastruktury na jego terytorium
        unrelated = self.proposal(1, 3)
        decided = self.proposal(1, 2, status='REJECTED')
        road, loan = self.road(1, 2), self.loan(2, 3)
        other_road, other_loan = self.road(1, 3), self.loan(3, 1)
        self.lose(2)
        counts = cancel_requests(db.session)
        db.session.commit(); db.session.expire_all()
        self.assertEqual(counts, {'diplomacy': 3, 'roads': 1, 'rail': 0, 'loans': 1})
        status = lambda model, id: db.session.get(model, id).status
        self.assertEqual([status(DiplomaticAction, i) for i in (to_lost, from_lost, permit)], ['EXPIRED'] * 3)
        self.assertEqual((status(DiplomaticAction, unrelated), status(DiplomaticAction, decided)), ('PENDING', 'REJECTED'))
        self.assertEqual((status(RoadProposal, road), status(StateLoan, loan)), ('cancelled', 'cancelled'))
        self.assertEqual((status(RoadProposal, other_road), status(StateLoan, other_loan)), ('pending', 'pending'))
        # Druga strona dostaje jedno zbiorcze powiadomienie; państwo bez niepodległości — żadnego.
        texts = {n.user_id: n.system_text for n in db.session.scalars(select(GameNotification))}
        self.assertIn('Anulowano 2 oczekujących wniosków', texts[1])
        self.assertIn('Państwo 2', texts[1])
        self.assertIn('Anulowano 2 oczekujących wniosków', texts[3])   # dołączenie do wojny + pożyczka
        self.assertNotIn(2, texts)
        self.assertEqual(cancel_requests(db.session), {'diplomacy': 0, 'roads': 0, 'rail': 0, 'loans': 0})   # idempotentne

    def test_nothing_without_lost_countries(self):
        self.proposal(1, 2)
        self.assertEqual(cancel_requests(db.session)['diplomacy'], 0)


class PagaPrivateMessageTests(FeatureTestCase):
    def test_paga_identity_cannot_send_but_player_can(self):
        from game.paga_ai_models import PagaAiIdentity
        from game.communication_models import PrivateMessage
        PagaAiIdentity.__table__.create(db.engine, checkfirst=True)
        self.assertEqual(self.post('/game/wiadomosci', content='Gracz pisze', recipient_id=2).status_code, 201)
        db.session.add(PagaAiIdentity(country_id=1, user_id=1)); db.session.commit()
        response = self.post('/game/wiadomosci', content='PAGA pisze', recipient_id=2)
        self.assertEqual(response.status_code, 403)
        self.assertIn('PAGA', response.json['error'])
        self.assertEqual(db.session.query(PrivateMessage).count(), 1)
