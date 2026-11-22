from datetime import timedelta
from uuid import uuid4
from unittest.mock import patch
from sqlalchemy import select
from sqlalchemy.orm import lazyload
from extensions import db
from models import DictStosunkiRelacja,DictStosunkiStan,Stosunki,Miasto
from test_game_commerce import CommerceFixture
from test_game_military import NOW
from game.trade_goods import AMMUNITION,trade_warehouse
from game.research_models import ResearchAccount,AmmunitionFactory
from game.commerce_models import TradeOffer,TradeShipment,ResourceStock,PortTariff,TradeReserveMovement
from game.finance_models import StateFinancialAccount
from game.forum_models import GameNotification
from game.finance_service import FinanceError
from game.trade_service import create_offer,cancel_offer,buy_offer,deliver_shipments,set_port_access,port_allows,set_tariff


class TradeExtensionTests(CommerceFixture):
    def setUp(self):
        super().setUp()
        db.session.add(ResearchAccount(panstwo_id=1,ammunition=100,points=0,nodes={}))
        self.relations={}
        for id,label in enumerate(['Złe','Egzystencjalnie wrogie','Sojusznicze','Partnerskie','Partnerskie strategiczne'],20):
            db.session.add(DictStosunkiRelacja(relacja_id=id,relacja_nazwa=label));self.relations[label]=id
        self.states={}
        for id,label in enumerate(['Wojna hybrydowa','Okupacja','Wojna kinetyczna (zamrożone)'],30):
            db.session.add(DictStosunkiStan(stan_id=id,stan_nazwa=label));self.states[label]=id
        db.session.commit()

    def offer(self,**extra):
        data={'request_id':str(uuid4()),'cargo':{'wegiel_kamienny':5},'price':'1000','port_id':101,'departure_rate':'0'}
        data.update(extra);return create_offer(1,data)

    def ammo_offer(self,**extra):
        return self.offer(**{'cargo':{AMMUNITION:10},**extra})

    def pair(self,relation=6,state=1,reverse=False):
        a,b=(2,1) if reverse else (1,2)
        row=db.session.scalar(select(Stosunki).options(lazyload('*')).where(Stosunki.PANSTWO_ID==a,Stosunki.PANSTWO_ID2==b))
        if row is None:row=Stosunki(PANSTWO_ID=a,PANSTWO_ID2=b);db.session.add(row)
        row.relacja_id=relation;row.stan_id=state;db.session.commit()

    def test_escrow_repeat_cancel_and_shared_ammunition_stock(self):
        key=str(uuid4());id=self.ammo_offer(request_id=key)
        self.assertEqual(self.ammo_offer(request_id=key),id)
        db.session.expire_all()
        self.assertEqual(db.session.get(ResearchAccount,1).ammunition,90)
        self.assertEqual(trade_warehouse(db.session,1)[AMMUNITION],{'available':90,'reserved':10,'total':100})
        cancel_offer(1,{'offer_id':id});cancel_offer(1,{'offer_id':id});db.session.expire_all()
        self.assertEqual(db.session.get(ResearchAccount,1).ammunition,100)
        self.assertIsNone(db.session.get(ResourceStock,(1,AMMUNITION)))

    def test_mixed_delivery_arrives_once_in_same_stock_used_by_defense(self):
        id=self.offer(cargo={AMMUNITION:10,'wegiel_kamienny':5});key=str(uuid4());shipment_id=self.buy(id,request_id=key)
        self.assertEqual(self.buy(id,request_id=key),shipment_id)
        db.session.expire_all()
        self.assertIsNone(db.session.get(ResearchAccount,2))
        row=db.session.get(TradeShipment,shipment_id);arrival=row.arrives_at
        deliver_shipments(db.session,arrival-timedelta(seconds=1));db.session.commit()
        self.assertIsNone(db.session.get(ResearchAccount,2))
        deliver_shipments(db.session,arrival+timedelta(days=1));db.session.commit()
        deliver_shipments(db.session,arrival+timedelta(days=2));db.session.commit()
        self.assertEqual(db.session.get(ResearchAccount,2).ammunition,10)
        self.assertEqual(db.session.get(ResourceStock,(2,'wegiel_kamienny')).quantity,5)
        self.assertEqual(db.session.get(TradeShipment,shipment_id).delivered_at,arrival)
        self.login(2);data=self.client.get('/game/handel/stan').json
        self.assertEqual(data['warehouse'][AMMUNITION]['available'],10)
        self.assertEqual(data['shipments'][0]['deliveredAt'],arrival.isoformat()+'Z')

    def test_insufficient_stock_rolls_back_entire_offer(self):
        with self.assertRaises(FinanceError):self.offer(cargo={AMMUNITION:101,'wegiel_kamienny':5})
        db.session.expire_all()
        self.assertEqual(db.session.get(ResearchAccount,1).ammunition,100)
        self.assertEqual(db.session.get(ResourceStock,(1,'wegiel_kamienny')).quantity,20)
        self.assertEqual(db.session.query(TradeOffer).count(),0)

    def test_hostile_relations_and_war_states_block_purchase_and_hide_offer(self):
        id=self.ammo_offer()
        restrictions=[(self.relations['Złe'],1),(10,1),(self.relations['Egzystencjalnie wrogie'],1),(6,8)]+[(6,state) for state in self.states.values()]
        for relation,state in restrictions:
            with self.subTest(relation=relation,state=state):
                self.pair(relation,state)
                with self.assertRaises(FinanceError):self.buy(id)
                self.login(2);data=self.client.get('/game/handel/stan').json
                self.assertNotIn(id,[offer['id'] for offer in data['offers']])
                self.assertEqual(db.session.get(StateFinancialAccount,2).reserve_balance,10000)
        self.assertEqual(db.session.query(TradeShipment).count(),0)
        self.assertEqual(db.session.query(GameNotification).count(),0)
        self.pair();self.buy(id)

    def test_reverse_direction_also_blocks_ammunition_but_not_ordinary_goods(self):
        self.pair(10,reverse=True)
        with self.assertRaises(FinanceError):self.buy(self.ammo_offer())
        self.assertIsNotNone(self.buy(self.offer()))

    def test_allied_port_access_overrides_global_and_legacy_selective_blocks(self):
        db.session.add(PortTariff(panstwo_id=1,rate=0,block_foreign=True,blocked_countries=[2]));db.session.commit()
        for label in ['Sojusznicze','Partnerskie','Partnerskie strategiczne']:
            self.pair(self.relations[label])
            db.session.expire_all()
            self.assertTrue(port_allows(db.session,1,2))
            with self.assertRaises(FinanceError):set_port_access(1,{'block_foreign':False,'blocked_countries':[2]})
            set_port_access(1,{'block_foreign':True,'blocked_countries':[]})
            db.session.expire_all();self.assertTrue(port_allows(db.session,1,2))
            self.login(1);data=self.client.get('/game/handel/stan').json
            self.assertIn(2,data['alliedCountryIds'])
        self.pair();self.assertFalse(port_allows(db.session,1,2))

    @patch('game.military_geography.region_adjacency',return_value={})   # 18 Nov 2026: test opłat — bez sąsiadów lądowych (reguła portu sąsiada: test_trade_neighbor_ports)
    def test_seller_notification_once_with_export_fee_ship_icon_and_trade_link(self,_adjacency):
        db.session.get(Miasto,101).czy_portowe='NIE';db.session.commit();set_tariff(3,{'rate':'5'})
        id=self.ammo_offer(port_id=103,departure_rate='5');key=str(uuid4());self.buy(id,request_id=key);self.buy(id,request_id=key)
        db.session.expire_all();notice=db.session.scalar(select(GameNotification))
        self.assertEqual(db.session.query(GameNotification).count(),1)
        self.assertEqual(notice.user_id,1)
        self.assertEqual(notice.system_text,'Państwo 2 zakupił/a 10 Amunicja przeciwrakietowa za 1 000,00 ROI. Cło portowe: 50,00 ROI')
        self.login(1);data=self.client.get('/game/forum/powiadomienia').json
        self.assertTrue(data['items'][0]['icon_url'].endswith('/CARGO%20SHIP.svg'))
        response=self.post(f'/game/forum/powiadomienia/{notice.id}/otworz')
        self.assertEqual(response.status_code,303);self.assertEqual(response.location,'/game/handel')

    def test_notification_failure_rolls_back_payment_and_purchase(self):
        id=self.ammo_offer()
        with patch('game.forum_models.GameNotification',side_effect=FinanceError('notification test')):
            with self.assertRaises(FinanceError):self.buy(id)
        db.session.expire_all()
        self.assertEqual(db.session.get(TradeOffer,id).status,'open')
        self.assertEqual(db.session.get(StateFinancialAccount,2).reserve_balance,10000)
        self.assertEqual(db.session.query(TradeShipment).count(),0)
        self.assertEqual(db.session.query(TradeReserveMovement).count(),0)

    def test_sunk_ammunition_is_not_credited(self):
        id=self.buy(self.ammo_offer());row=db.session.get(TradeShipment,id)
        row.health=0;row.sunk_at=NOW;db.session.commit()
        deliver_shipments(db.session,NOW+timedelta(days=2));db.session.commit()
        self.assertIsNone(db.session.get(ResearchAccount,2))
        self.assertIsNone(db.session.get(TradeShipment,id).delivered_at)

    # Production test: grid with enough energy (since 10 Nov 2026 a deficit stops factories; see test_infrastructure_effects).
    @patch('game.industry_service.powered_factories',new=lambda session,factories,production,resident:{f.id for f in factories})
    def test_complete_factory_days_are_available_for_offer(self):
        db.session.get(ResearchAccount,1).ammunition=0
        db.session.add(AmmunitionFactory(panstwo_id=1,region_id=1,budget_id=1,map_x=1,map_y=1,cost=1,produced_at=NOW-timedelta(days=2),created_game_at=NOW-timedelta(days=2),request_id=str(uuid4()),production_target=10**6))
        db.session.add_all([ResourceStock(panstwo_id=1,resource=code,quantity=100) for code in ('zelazo','ropa_naftowa')]);db.session.commit();self.ammo_offer(cargo={AMMUNITION:10});db.session.expire_all()
        self.assertEqual(db.session.get(ResearchAccount,1).ammunition,0)
        self.assertEqual(trade_warehouse(db.session,1)[AMMUNITION]['reserved'],10)
