"""Foreign concessions, accounting, extraction, seizure and the 180-day boundary."""
from datetime import timedelta
from uuid import uuid4
from unittest.mock import patch
from sqlalchemy import select,text
from extensions import db
from models import Region,RegionZasob
from game.commerce_models import Mine,MiningExpense,ResourceStock
from game.industry_models import IndustryMovement
from game.diplomacy_models import DiplomaticAction
from game.foreign_mining import allowed,host_may_remove,seize
from game.mining_service import extract_country
from test_game_commerce import CommerceFixture,NOW


class ForeignMiningTests(CommerceFixture):
    def permit(self):
        from game.diplomacy_service import create_action,decide_action
        from game.intelligence_models import IntelligenceMission,IntelligenceAgent
        # The country owner is the host; the existing player builds abroad.
        region=db.session.get(Region,1);region.panstwo_id=2
        db.session.add(IntelligenceAgent(id=777,panstwo_id=1,level=1))
        db.session.flush()
        db.session.add(IntelligenceMission(panstwo_id=1,agent_id=777,region_id=1,target_country_id=2,region_name='Region',kind='resources',starts_at=NOW-timedelta(days=8),ends_at=NOW-timedelta(days=1),completed_at=NOW,success=True,report={'entries':[{'label':'Węgiel','value':'3'}]}))
        db.session.commit()
        action=create_action(db.session,1,2,'MINING_PERMIT',None,NOW,sender_user_id=1,params={'region_id':1})
        db.session.commit()
        self.assertEqual(decide_action(db.session,action.id,2,True,NOW,user_id=2),'ACCEPTED')
        db.session.commit()
        return action

    def test_permission_required_and_granted(self):
        action=self.permit()
        self.assertTrue(allowed(db.session,1,db.session.get(Region,1)))
        self.assertFalse(allowed(db.session,3,db.session.get(Region,1)))
        self.assertEqual(action.kind,'MINING_PERMIT')

    def test_double_cost_host_receipt_and_guest_extraction(self):
        self.permit()
        # Host current budget: mirror the existing budget period.
        db.session.execute(text("INSERT INTO game_state_budgets (id,panstwo_id,game_year,period) SELECT 2,2,game_year,period FROM game_state_budgets WHERE id=1"))
        db.session.commit()
        mid=self.mine();db.session.expire_all();mine=db.session.get(Mine,mid)
        self.assertEqual(db.session.scalar(select(MiningExpense.amount).where(MiningExpense.mine_id==mid)),4000000000)
        self.assertEqual(db.session.scalar(select(IndustryMovement.amount).where(IndustryMovement.panstwo_id==2)),-2000000000)
        self.assertEqual(mine.pollution_points,2)
        extract_country(db.session,1,NOW+timedelta(days=6));db.session.commit()
        self.assertEqual(db.session.get(ResourceStock,(1,'wegiel_kamienny')).quantity,21)
        self.assertFalse(host_may_remove(db.session,mine,2,mine.ready_at+timedelta(days=180)-timedelta(seconds=1)))
        self.assertTrue(host_may_remove(db.session,mine,2,mine.ready_at+timedelta(days=180)))
        seize(db.session,1,3,NOW+timedelta(days=6));db.session.commit()
        self.assertEqual(mine.panstwo_id,3)
        extract_country(db.session,3,NOW+timedelta(days=7));db.session.commit()
        self.assertEqual(db.session.get(ResourceStock,(3,'wegiel_kamienny')).quantity,1)

    def test_request_requires_successful_resource_report(self):
        from game.diplomacy_service import create_action,DiplomacyError
        with self.assertRaises(DiplomacyError):
            create_action(db.session,1,2,'MINING_PERMIT',None,NOW,sender_user_id=1,params={'region_id':2})

    def test_host_removal_endpoint_respects_age_and_no_refund(self):
        from game.industry_service import change_industry
        from game.finance_service import FinanceError
        mid=self.mine();db.session.expire_all()
        mine=db.session.get(Mine,mid);mine.panstwo_id=2;db.session.commit()
        data={'category':'mine','action':'remove','object_id':mid,'request_id':str(uuid4())}
        with patch('game.industry_service.game_now',return_value=mine.ready_at+timedelta(days=179)),patch('game.research_service.settle_production'):
            with self.assertRaises(FinanceError):change_industry(1,data)
        with patch('game.industry_service.game_now',return_value=mine.ready_at+timedelta(days=180)),patch('game.research_service.settle_production'):
            change_industry(1,data)
        db.session.expire_all()
        self.assertIsNotNone(db.session.get(Mine,mid).removed_at)
        self.assertEqual(db.session.scalar(select(IndustryMovement.amount).where(IndustryMovement.request_id==data['request_id'])),0)

    def test_host_sees_foreign_mine_without_intelligence(self):
        from game.military import visible_mines
        mid=self.mine();db.session.expire_all()
        mine=db.session.get(Mine,mid);mine.panstwo_id=2;db.session.commit()
        self.assertIn(mid,{m['id'] for m in visible_mines(1,True)})

    def test_host_can_attack_foreign_mine_only_during_war(self):
        from game.military_service import create_order
        from game.military_models import MilitaryFlight
        from models import Stosunki
        from game.finance_service import FinanceError
        mid=self.mine();db.session.expire_all();mine=db.session.get(Mine,mid);mine.panstwo_id=2;mine.map_x=100;mine.map_y=0
        base=self.base();base.map_x=0;base.map_y=0;base.garrison={'launchers':1};db.session.commit()
        data={'source_base_id':base.id,'kind':'missile','target_mine_id':mid,'missile_type':'short','missiles':2}
        with self.assertRaises(FinanceError):create_order(1,data)
        db.session.add(Stosunki(PANSTWO_ID=1,PANSTWO_ID2=2,stan_id=8));db.session.commit()
        create_order(1,data);db.session.expire_all()
        flight=db.session.scalar(select(MilitaryFlight).where(MilitaryFlight.target_mine_id==mid))
        self.assertEqual(flight.target_country_id,2)

    def test_map_preserves_region_without_sovereign_host(self):
        from models import Panstwo
        from game.foreign_mining import map_regions,eligible
        from sqlalchemy import update
        db.session.execute(update(Panstwo).where(Panstwo.PANSTWO_ID==4).values(czy_suwerenny='NIE'))
        db.session.add(Region(region_id=3,panstwo_id=4,region_nazwa='Bez gospodarza'))
        db.session.commit()
        data=map_regions(db.session,1)
        self.assertIn('3',data)
        self.assertIsNone(data['3']['countryId'])
        self.assertFalse(data['3']['canRequest'])
        self.assertFalse(eligible(db.session,1,None))

    def test_paga_adapter_handles_map_without_host(self):
        from types import SimpleNamespace
        from game.paga2.mines_abroad import propose
        from models import Panstwo
        from sqlalchemy import update
        db.session.execute(update(Panstwo).where(Panstwo.PANSTWO_ID==4).values(czy_suwerenny='NIE'))
        db.session.add(Region(region_id=3,panstwo_id=4,region_nazwa='Bez gospodarza'))
        db.session.commit()
        self.assertEqual(propose(SimpleNamespace(country_id=1)),[])
