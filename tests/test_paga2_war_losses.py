"""13 Nov 2026: PAGA2 — straty wojenne skłaniają do pokoju/rozejmu; pokój po ciężkiej wojnie odstrasza od kolejnej."""
from datetime import timedelta
from types import SimpleNamespace
from extensions import db
from models import AudytStosunki,Stosunki,DictStosunkiRelacja
from test_game_military_flights import FlightFixture
from test_game_military import NOW
from game.military_models import MilitaryFlight,MilitaryOrder
from game.paga2 import war_losses


class WarLossTests(FlightFixture):
    def audit(self,a,b,state,when):
        db.session.add(AudytStosunki(panstwo_id=min(a,b),panstwo_id2=max(a,b),relacja_id=10,stan_id=state,data_zmiany_entenda=when,data_zmiany_rzeczywista=when));db.session.commit()

    def hit(self,attacker,victim,when,is_nuclear=False,missiles=1,**damage):
        order=MilitaryOrder(panstwo_id=attacker,user_id=attacker,region_id=1,kind='missile',payload={});db.session.add(order);db.session.flush()
        db.session.add(MilitaryFlight(order_id=order.id,panstwo_id=attacker,target_country_id=victim,kind='missile',missile_type='short',missiles=missiles,is_nuclear=is_nuclear,source_x=0,source_y=0,target_x=1,target_y=0,
                                      distance_km=1,starts_at=when,impact_at=when,impacted_at=when,damage=damage));db.session.commit()

    def paga(self,country=1,loss_tolerance=50,now=NOW):
        return SimpleNamespace(country_id=country,now=now,traits={'loss_tolerance':loss_tolerance})

    def test_losses_in_current_war_raise_peace_bonus(self):
        self.audit(1,2,8,NOW-timedelta(days=60))
        self.hit(2,1,NOW-timedelta(days=90),baseDestroyed=True)        # przed wojną — nie liczy się
        self.hit(2,1,NOW-timedelta(days=30),baseDestroyed=True)
        self.hit(2,1,NOW-timedelta(days=20),factoryDestroyed=True)
        self.hit(2,1,NOW-timedelta(days=10),powerDestroyed=True)
        self.hit(2,1,NOW-timedelta(days=5),infrastructure='road',infrastructurePoints=20)
        self.hit(2,1,NOW-timedelta(days=4),nuclear=True,destroyed={'bases':1,'factories':0,'power':1},infrastructureLoss={'road':50,'rail':50})
        points,loss,days=war_losses.current_war(self.paga(),2)
        self.assertEqual(loss,{'bases':2,'factories':1,'power':2,'infrastructure':120,'nuclear':0});self.assertEqual(days,60)
        self.assertEqual(points,3*2+2*1+2*2+0.2*120)
        self.assertEqual(war_losses.peace_bonus(self.paga(),2)[0],1.0+war_losses.LOSS_PEACE_MAX+1.0)   # limit premii za straty + zmęczenie wojną (60 dni)
        from unittest.mock import patch
        with patch('game.paga2.war_losses.current_war',return_value=(5.0,{},0)):
            careful,_,_=war_losses.peace_bonus(self.paga(loss_tolerance=10),2)
            brave,_,_=war_losses.peace_bonus(self.paga(loss_tolerance=90),2)
        self.assertGreater(careful,brave);self.assertGreater(brave,1.0)   # niska tolerancja strat — silniejsza skłonność do pokoju
        calm,_,_=war_losses.peace_bonus(self.paga(),3)   # brak wojny z państwem 3
        self.assertEqual(calm,1.0)

    def test_peace_after_heavy_losses_deters_new_aggression_and_against_allies(self):
        db.session.add(DictStosunkiRelacja(relacja_id=20,relacja_nazwa='Sojusznicze'));db.session.commit()
        db.session.add(Stosunki(PANSTWO_ID=2,PANSTWO_ID2=3,relacja_id=20,stan_id=1));db.session.commit()
        self.audit(1,2,8,NOW-timedelta(days=200));self.audit(1,2,1,NOW-timedelta(days=100))   # wojna → pokój
        for day in (190,180,170,160):self.hit(2,1,NOW-timedelta(days=day),baseDestroyed=True)
        deterred=war_losses.deterrence_map(self.paga())
        self.assertGreater(deterred.get(2,0),0);self.assertAlmostEqual(deterred.get(3,0),war_losses.ALLY_SHARE*deterred[2])
        self.assertNotIn(4,deterred)
        later=war_losses.deterrence_map(self.paga(now=NOW+timedelta(days=365*3)))
        self.assertEqual(later.get(2,0),0)   # kara wygasa po 3 latach Entendy

    def test_light_war_does_not_deter(self):
        self.audit(1,2,8,NOW-timedelta(days=200));self.audit(1,2,1,NOW-timedelta(days=100))
        self.hit(2,1,NOW-timedelta(days=150),baseDestroyed=True)   # 3 pkt < próg 10
        self.assertEqual(war_losses.deterrence_map(self.paga()),{})


class NuclearPeaceTests(WarLossTests):
    """13 Nov 2026: po użyciu broni atomowej przeciw państwu PAGA2 jest ono drastycznie bardziej skłonne do pokoju."""
    def test_nuclear_use_drastically_raises_peace_bonus(self):
        self.audit(1,2,8,NOW-timedelta(days=10))
        base,_,_=war_losses.peace_bonus(self.paga(),2)
        self.hit(2,1,NOW-timedelta(days=5),is_nuclear=True)                       # także przechwycona rakieta to użycie broni atomowej
        war_ctx=self.paga();bonus,loss,_=war_losses.peace_bonus(war_ctx,2)
        self.assertEqual(loss['nuclear'],1);self.assertGreaterEqual(bonus-base,war_losses.NUCLEAR_PEACE)
        self.hit(2,1,NOW-timedelta(days=4),is_nuclear=True,missiles=2)
        more,_,_=war_losses.peace_bonus(self.paga(),2);self.assertAlmostEqual(more-bonus,2*war_losses.NUCLEAR_PEACE_EXTRA)
        self.hit(2,1,NOW-timedelta(days=3),is_nuclear=True,missiles=10)
        capped,_,_=war_losses.peace_bonus(self.paga(),2);self.assertLessEqual(capped-base,war_losses.NUCLEAR_PEACE_MAX)
        self.hit(3,1,NOW-timedelta(days=2),is_nuclear=True)                       # inne państwo — nie wpływa na pokój z państwem 2
        self.assertEqual(war_losses.peace_bonus(self.paga(),2)[0],capped)

    def test_peace_terms_show_note_and_proposal_acceptance_wins(self):
        from game.paga2 import diplomacy
        self.audit(1,2,8,NOW-timedelta(days=10));self.hit(2,1,NOW-timedelta(days=5),is_nuclear=True)
        ctx=self.paga();ctx.situation={'occupied_regions':{}};ctx.history=lambda other:{'hostile_from':0}
        with __import__('unittest.mock',fromlist=['patch']).patch('game.paga2.diplomacy.weakness',return_value=0.0):terms=diplomacy.peace_terms(ctx,2)
        self.assertGreaterEqual(terms['base'],war_losses.NUCLEAR_PEACE);self.assertTrue(any('broni atomowej' in note for note in terms['notes']))
