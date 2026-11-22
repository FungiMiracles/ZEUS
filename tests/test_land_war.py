"""Wojska lądowe (11 Nov 2026): wyszkolenie w WIKI, obrona miast, inwazja, bitwa, okupacja, aneksja."""
import uuid
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from flask import Flask
from sqlalchemy import select
from extensions import db
from models import Wojsko, Miasto, Region, Stosunki, Panstwo
from test_game_military import MilitaryFixture, NOW
from game.military_models import MilitaryBase
from game.land_war_models import LandArmy, Occupation
from game.finance_service import FinanceError
from game.forum_models import GameNotification
from game import land_war


def key():return str(uuid.uuid4())


class LandWarFixture(MilitaryFixture):
    def setUp(self):
        super().setUp()
        from game.land_war_models import TrainingExpense,SovereigntyLoss
        for model in (LandArmy,Occupation,TrainingExpense,SovereigntyLoss):model.__table__.create(db.engine,checkfirst=True)
        from sqlalchemy import text   # GDP history of annexations; INTEGER PRIMARY KEY autoincrements in SQLite (BigInteger does not)
        with db.engine.begin() as connection:connection.execute(text('CREATE TABLE IF NOT EXISTS pkb_state_history (id INTEGER PRIMARY KEY, panstwo_id INTEGER NOT NULL, '
            'data_entenda DATE NOT NULL, data_rzeczywista DATETIME NOT NULL, source VARCHAR(100) NOT NULL, event_id BIGINT, old_pkb BIGINT, new_pkb BIGINT, change_delta BIGINT, '
            'CONSTRAINT uq_pkb_state_once UNIQUE (panstwo_id, data_entenda, source))'))
        self.now=NOW
        for target in ('game.land_war.game_now','game.military.game_now'):
            clock=patch(target,side_effect=lambda:self.now);clock.start();self.addCleanup(clock.stop)
        self.player=1
        who=patch('game.finance_service._country_for_user',side_effect=lambda session,user_id,lock=False:SimpleNamespace(PANSTWO_ID=self.player));who.start();self.addCleanup(who.stop)
        for target,value in [('game.road_projects.neighboring_countries',{2}),('game.land_war.border_fraction',0.5),('game.land_war.overland',True),('game.military_geography.city_point',[60,0])]:
            p=patch(target,return_value=value);p.start();self.addCleanup(p.stop)
        from sqlalchemy import update
        db.session.execute(update(Panstwo).where(Panstwo.PANSTWO_ID==1).values(panstwo_PKB=1000000000000,panstwo_populacja=1000000))   # PKB per capita 1 000 000 -> +10 000 / jednostkę
        db.session.add(Wojsko(panstwo_id=2,liczba_baz_ladowych=2,wojska_ladowe_ilosc=50000,czolgi_ilosc=100,wozy_opancerzone_ilosc=100,wyszkolenie_ladowe=700))
        army=db.session.query(Wojsko).filter_by(panstwo_id=1).one();army.wyszkolenie_ladowe=300
        db.session.add(Stosunki(PANSTWO_ID=1,PANSTWO_ID2=2,stan_id=8))
        db.session.add(Region(region_id=3,panstwo_id=2,region_nazwa='Trzeci region'))
        self.home=MilitaryBase(panstwo_id=1,region_id=1,kind='land',level=7,garrison={'soldiers':5000,'armored':20,'tanks':10},map_x=0,map_y=0)
        self.enemy=MilitaryBase(panstwo_id=2,region_id=2,kind='land',level=1,garrison={'soldiers':500,'armored':0,'tanks':0},map_x=100,map_y=0)
        db.session.add_all([self.home,self.enemy])
        db.session.add(Miasto(miasto_id=10,panstwo_id=2,miasto_nazwa='Miasto B',region_id=2,czy_na_mapie='TAK',miasto_populacja=1000))
        db.session.add(Miasto(miasto_id=11,panstwo_id=1,miasto_nazwa='Miasto A',region_id=1,czy_na_mapie='TAK',miasto_populacja=1000))
        db.session.commit()
        known=patch('game.intelligence_service.known_ids',return_value={self.enemy.id});known.start();self.addCleanup(known.stop)
    def invade(self,target_kind='base',target_id=None,**units):
        data={'source_base_id':self.home.id,'target_kind':target_kind,'target_id':target_id or self.enemy.id,'request_id':key(),'soldiers':0,'armored':0,'tanks':0,**units}
        return land_war.launch_invasion(1,data)
    def army(self,id):db.session.expire_all();return db.session.get(LandArmy,id)
    def arrive(self,army_id,rolls):
        """Move the clock to the army's arrival and fight with fixed chance factors."""
        army=self.army(army_id);self.now=army.arrives_at
        with patch.object(land_war._random,'uniform',side_effect=list(rolls)):
            from sqlalchemy.orm import Session
            with Session(db.engine) as session,session.begin():land_war.complete_marches(session,self.now)
        return self.army(army_id)


class TrainingWikiTests(LandWarFixture):
    def test_wiki_add_and_edit_validate_training_0_to_1000(self):
        import routes_armia
        app=self.app
        captured={}
        def render(template,**context):captured.update(template=template,**context);return 'ok'
        country=lambda id:SimpleNamespace(PANSTWO_ID=id,panstwo_nazwa=f'Państwo {id}')
        stub=SimpleNamespace(query=SimpleNamespace(get_or_404=country,get=country))   # SQLite fixture lacks the Panstwo relationship tables
        with patch.object(routes_armia,'Panstwo',stub),patch.object(routes_armia,'render_template',side_effect=render),patch.object(routes_armia,'flash'),patch.object(routes_armia,'redirect',return_value='redirect'),patch.object(routes_armia,'url_for',return_value='/x'):
            routes_armia.init_armia_routes(app)
            client=app.test_client()
            with client.session_transaction() as browser:browser['rola']='wszechmocny'
            form={field:'1' for field in ['wojska_ladowe_ilosc','wojska_morskie_ilosc','wojska_powietrzne_ilosc','procent_PKB']}
            form.update({'wyszkolenie_ladowe':'1001','wyszkolenie_morskie':'0','wyszkolenie_powietrzne':'1000'})
            for field in ['czolgi_ilosc','mysliwce_ilosc','okrety_wojenne_ilosc','lotniskowce_ilosc','okrety_podwodne_ilosc','wyrzutnie_rakiet_ilosc','wozy_opancerzone_ilosc','drony_ilosc','bron_atomowa_ilosc','rakiety_krotkiego_zasiegu','rakiety_sredniego_zasiegu','rakiety_dalekiego_zasiegu','liczba_baz_ladowych','liczba_baz_morskich','liczba_baz_powietrznych']:form[field]='0'
            client.post('/wojsko/2/edit',data=form)
            self.assertIn('od 0 do 1000',captured.get('error',''))
            client.post('/wojsko/2/edit',data={**form,'wyszkolenie_ladowe':'850'})
            db.session.expire_all();row=db.session.query(Wojsko).filter_by(panstwo_id=2).one()
            self.assertEqual((row.wyszkolenie_ladowe,row.wyszkolenie_morskie,row.wyszkolenie_powietrzne),(850,0,1000))
            captured.clear();client.post('/wojsko_form_add',data={**form,'panstwo_id':'3','wyszkolenie_ladowe':'-1'})
            self.assertIn('od 0 do 1000',captured.get('error',''))
            client.post('/wojsko_form_add',data={**form,'panstwo_id':'3','wyszkolenie_ladowe':'250'})
            db.session.expire_all();self.assertEqual(db.session.query(Wojsko).filter_by(panstwo_id=3).one().wyszkolenie_ladowe,250)

    def test_templates_show_and_edit_training(self):
        from pathlib import Path
        root=Path(__file__).resolve().parents[1]/'templates'
        self.assertIn('training_rows(wojsko)',(root/'wojsko_form.html').read_text())
        for name in ('wojsko_form_add.html','wojsko_form_edit.html'):
            text=(root/name).read_text()
            for field in ('wyszkolenie_ladowe','wyszkolenie_morskie','wyszkolenie_powietrzne'):self.assertIn(field,text)
            self.assertIn('max="1000"',text)


class CityDefenseTests(LandWarFixture):
    def test_defense_moves_units_from_base_and_back(self):
        id=land_war.add_city_defense(1,{'city_id':11,'base_id':self.home.id,'soldiers':300,'armored':2,'tanks':1,'request_id':key()})
        db.session.expire_all();home=db.session.get(MilitaryBase,self.home.id)
        self.assertEqual(home.garrison,{'soldiers':4700,'armored':18,'tanks':9})
        army=self.army(id);self.assertEqual((army.status,army.role,army.target_city_id),('DEFENDING','city_defense',11))
        # The units stay allocated from the totals (they cannot be deployed twice).
        from game.military_service import active_counts
        active=active_counts([home],db.session,1);self.assertEqual((active['wojska_ladowe_ilosc'],active['wozy_opancerzone_ilosc'],active['czolgi_ilosc']),(5000,20,10))
        with self.assertRaises(FinanceError):land_war.add_city_defense(1,{'city_id':10,'base_id':self.home.id,'soldiers':1,'request_id':key()})   # not our city
        # Only a base in the city's own region can send defenders.
        db.session.add(Miasto(miasto_id=12,panstwo_id=1,miasto_nazwa='Miasto C',region_id=4,czy_na_mapie='TAK',miasto_populacja=10));db.session.commit()
        with self.assertRaises(FinanceError) as error:land_war.add_city_defense(1,{'city_id':12,'base_id':self.home.id,'soldiers':1,'request_id':key()})
        self.assertIn('tym samym regionie',str(error.exception))
        with self.assertRaises(FinanceError):land_war.add_city_defense(1,{'city_id':11,'base_id':self.home.id,'soldiers':999999,'request_id':key()})
        land_war.withdraw_city_defense(1,{'army_id':id})
        db.session.expire_all();self.assertEqual(db.session.get(MilitaryBase,self.home.id).garrison,{'soldiers':5000,'armored':20,'tanks':10})
        self.assertEqual(self.army(id).status,'WITHDRAWN')


class InvasionTests(LandWarFixture):
    def test_conditions_war_and_border(self):
        db.session.query(Stosunki).delete();db.session.commit()
        with self.assertRaises(FinanceError) as error:self.invade(soldiers=10)
        self.assertIn('wojna',str(error.exception))
        db.session.add(Stosunki(PANSTWO_ID=1,PANSTWO_ID2=2,stan_id=8));db.session.commit()
        with patch('game.road_projects.neighboring_countries',return_value=set()),self.assertRaises(FinanceError) as error:self.invade(soldiers=10)
        self.assertIn('graniczyć',str(error.exception))
        with self.assertRaises(FinanceError):self.invade(soldiers=0)
        with self.assertRaises(FinanceError):self.invade(soldiers=10**6)

    def test_cost_speed_route_and_border_notification(self):
        id=self.invade(soldiers=100,armored=0,tanks=2)
        army=self.army(id)
        # (10 000 + 10 000) × 100 + (50 000 + 10 000) × 2
        self.assertEqual(army.cost,Decimal('2120000.00'));self.assertEqual(army.speed_kmh,50)
        self.assertEqual(army.arrives_at,NOW+timedelta(hours=2));self.assertEqual(army.border_at,NOW+timedelta(hours=1))
        db.session.expire_all();self.assertEqual(db.session.get(MilitaryBase,self.home.id).garrison,{'soldiers':4900,'armored':20,'tanks':8})
        self.assertEqual(self.army(self.invade(soldiers=1,armored=1)).speed_kmh,80)
        from game.military_service import military_budget
        _,total,available=military_budget(db.session,1);self.assertLessEqual(available,total-army.cost)
        self.now=NOW+timedelta(minutes=61)
        from sqlalchemy.orm import Session
        with Session(db.engine) as session,session.begin():land_war.complete_marches(session,self.now)
        self.assertTrue(self.army(id).border_notified)
        self.assertTrue(any('Wtargnięcie' in (n.system_text or '') for n in db.session.query(GameNotification).filter_by(user_id=2)))
        self.assertEqual(self.army(id).status,'MARCHING')

    def test_budget_must_cover_the_cost(self):
        self.set_budget(1000)
        with self.assertRaises(FinanceError) as error:self.invade(soldiers=100)
        self.assertIn('budżecie sił zbrojnych',str(error.exception))

    def test_example_battle_attacker_wins_with_proportional_losses(self):
        # Administrator's example: 1000 soldiers at 300 vs 500 soldiers at 700; chance 0.3 vs 0.1 -> 3900 vs 3850.
        self.home.garrison={'soldiers':1000,'armored':0,'tanks':0};db.session.commit()
        id=self.invade(soldiers=1000)
        army=self.arrive(id,[0.3,0.1])
        battle=army.battle
        self.assertEqual((battle['attacker']['final'],battle['defender']['final'],battle['result']),(3900.0,3850.0,'ATTACKER_WON'))
        self.assertEqual(army.status,'OCCUPYING');self.assertEqual(army.soldiers,1000-round(1000*3850/3900))
        db.session.expire_all()
        self.assertEqual(db.session.get(MilitaryBase,self.enemy.id).garrison['soldiers'],0)
        self.assertEqual(db.session.query(Wojsko).filter_by(panstwo_id=2).one().wojska_ladowe_ilosc,50000-500)
        self.assertEqual(db.session.query(Wojsko).filter_by(panstwo_id=1).one().wojska_ladowe_ilosc,100000-round(1000*3850/3900))
        occupation=db.session.scalar(select(Occupation).where(Occupation.kind=='base'))
        self.assertEqual((occupation.base_id,occupation.occupier_id,occupation.owner_id,occupation.status),(self.enemy.id,1,2,'ACTIVE'))

    def test_weights_and_defeat_loses_everything(self):
        # 10 tanks × 5 × 3.0 = 150 vs 500 soldiers × 7.0 = 3500 -> attacker destroyed, nothing returns.
        id=self.invade(tanks=10)
        army=self.arrive(id,[0.5,0.0])
        self.assertEqual((army.status,army.tanks,army.battle['result']),('DESTROYED',0,'DEFENDER_WON'))
        self.assertEqual(army.battle['attacker']['strength'],150.0)
        db.session.expire_all();self.assertEqual(db.session.query(Wojsko).filter_by(panstwo_id=1).one().czolgi_ilosc,490)
        self.assertEqual(db.session.get(MilitaryBase,self.home.id).garrison['tanks'],0)
        # Defenders lose in proportion 225/3500 of their units.
        self.assertEqual(db.session.get(MilitaryBase,self.enemy.id).garrison['soldiers'],500-round(500*225/3500))

    def test_tie_goes_to_the_defender(self):
        self.enemy.garrison={'soldiers':300};db.session.add(self.enemy)
        db.session.query(Wojsko).filter_by(panstwo_id=2).one().wyszkolenie_ladowe=300;db.session.commit()
        self.assertEqual(self.arrive(self.invade(soldiers=300),[0.2,0.2]).battle['result'],'DEFENDER_WON')

    def test_city_attack_fights_city_defenders(self):
        self.player=2
        land_war.add_city_defense(2,{'city_id':10,'base_id':self.enemy.id,'soldiers':200,'request_id':key()})
        self.player=1
        army=self.arrive(self.invade('city',10,soldiers=2000),[0.0,0.0])
        self.assertEqual(army.battle['defender']['units']['soldiers'],200);self.assertEqual(army.status,'OCCUPYING')
        self.assertEqual(db.session.scalar(select(LandArmy.status).where(LandArmy.panstwo_id==2)),'DESTROYED')
        self.assertEqual(db.session.scalar(select(Occupation.city_id).where(Occupation.kind=='city')),10)


class OccupationTests(LandWarFixture):
    def conquer_region(self):
        self.arrive(self.invade(soldiers=3000),[0.0,0.0])
        self.arrive(self.invade('city',10,soldiers=100),[0.0,0.0])
        return db.session.scalar(select(Occupation).where(Occupation.kind=='region'))

    def test_occupied_base_cannot_be_used_by_its_owner(self):
        self.arrive(self.invade(soldiers=3000),[0.0,0.0])
        self.player=2
        with self.assertRaises(FinanceError) as error:land_war.add_city_defense(2,{'city_id':10,'base_id':self.enemy.id,'soldiers':1,'request_id':key()})
        self.assertIn('okupowana',str(error.exception))
        with patch('game.military_service._country_for_user',return_value=SimpleNamespace(PANSTWO_ID=2)),self.assertRaises(FinanceError):
            from game.military_service import change_defense
            change_defense(2,'rename',{'base_id':self.enemy.id,'name':'X'})

    def test_region_question_occupation_and_annexation_after_30_days(self):
        from sqlalchemy import update
        from models import PKBStateHistory
        db.session.execute(update(Panstwo).where(Panstwo.PANSTWO_ID==2).values(panstwo_PKB=10000000,panstwo_populacja=10000))
        db.session.execute(update(Region).where(Region.region_id==2).values(region_ludnosc_pozamiejska=1000,region_powierzchnia=30))
        db.session.execute(update(Region).where(Region.region_id==3).values(region_ludnosc_pozamiejska=500,region_powierzchnia=70))
        db.session.commit()
        row=self.conquer_region()
        self.assertEqual((row.status,row.region_id,row.occupier_id),('PENDING',2,1))
        self.assertTrue(any('Zdecyduj' in (n.system_text or '') for n in db.session.query(GameNotification).filter_by(user_id=1)))
        land_war.decide_region(1,{'occupation_id':row.id,'occupy':True})
        db.session.expire_all();row=db.session.get(Occupation,row.id);self.assertEqual(row.status,'ACTIVE')
        with self.assertRaises(FinanceError) as error:land_war.annex_region(1,{'occupation_id':row.id})
        self.assertIn('30 dniach',str(error.exception))
        self.now=row.started_at+timedelta(days=30)
        land_war.annex_region(1,{'occupation_id':row.id})
        db.session.expire_all()
        self.assertEqual(db.session.get(Region,2).panstwo_id,1);self.assertEqual(db.session.get(Miasto,10).panstwo_id,1)
        base=db.session.get(MilitaryBase,self.enemy.id);self.assertEqual(base.panstwo_id,1);self.assertGreater(base.garrison['soldiers'],0)
        self.assertEqual(db.session.get(Occupation,row.id).status,'ANNEXED')
        # GDP per capita of the owner (10 000 000 / 10 000 = 1 000) × region population (1 000 rural + 1 000 in Miasto B)
        stats=lambda id:db.session.execute(select(Panstwo.panstwo_PKB,Panstwo.panstwo_populacja,Panstwo.panstwo_powierzchnia).where(Panstwo.PANSTWO_ID==id)).one()
        winner,loser=stats(1),stats(2)
        self.assertEqual((winner.panstwo_PKB,loser.panstwo_PKB),(1000000000000+2000000,8000000))
        self.assertEqual((loser.panstwo_populacja,loser.panstwo_powierzchnia),(500,70),'the owner keeps only region 3')
        self.assertEqual(winner.panstwo_populacja,sum(r.region_populacja for r in db.session.query(Region).filter_by(panstwo_id=1)))
        history={(h.panstwo_id,h.change_delta) for h in db.session.query(PKBStateHistory).filter_by(source='ANEKSJA')}
        self.assertEqual(history,{(1,2000000),(2,-2000000)})

    def test_declining_keeps_troops_without_occupation(self):
        row=self.conquer_region()
        land_war.decide_region(1,{'occupation_id':row.id,'occupy':False})
        db.session.expire_all();self.assertEqual(db.session.get(Occupation,row.id).status,'DECLINED')
        self.assertEqual(db.session.get(Region,2).panstwo_id,2)
        with self.assertRaises(FinanceError):land_war.annex_region(1,{'occupation_id':row.id})

    def recapture_setup(self):
        row=self.conquer_region();land_war.decide_region(1,{'occupation_id':row.id,'occupy':True})
        from sqlalchemy import text
        db.session.execute(text("INSERT INTO game_state_budgets (id,panstwo_id,game_year,period) VALUES (2,2,2990,1)"))
        db.session.execute(text("INSERT INTO game_state_budget_allocations (id,budget_id,category_code,amount) VALUES (2,2,'armed_forces',1000000000000)"))
        reserve=MilitaryBase(panstwo_id=2,region_id=3,kind='land',level=7,garrison={'soldiers':45000,'armored':0,'tanks':0},map_x=200,map_y=0);db.session.add(reserve);db.session.commit()
        self.player=2
        return row,reserve
    def recapture(self,reserve,kind,target,soldiers):
        with patch('game.road_projects.neighboring_countries',return_value=set()):
            id=land_war.launch_invasion(2,{'source_base_id':reserve.id,'target_kind':kind,'target_id':target,'soldiers':soldiers,'request_id':key()})
        return self.arrive(id,[0.0,0.0])

    def test_owner_recaptures_and_ends_region_occupation(self):
        row,reserve=self.recapture_setup()
        # The owner retakes the city from its own land base elsewhere (recapture: no border requirement).
        army=self.recapture(reserve,'city',10,20000)
        self.assertEqual((army.battle['result'],army.status),('ATTACKER_WON','DEFENDING'))
        db.session.expire_all()
        self.assertEqual(db.session.scalar(select(Occupation.status).where(Occupation.kind=='city')),'ENDED')
        # The base is still held: the region stays occupied (and closed to construction) and cannot be annexed.
        self.assertEqual(db.session.get(Occupation,row.id).status,'ACTIVE')
        self.assertTrue(any('pozostaje okupowany' in (n.system_text or '') for n in db.session.query(GameNotification)))
        self.now=self.now+timedelta(days=31);self.player=1
        with self.assertRaises(FinanceError) as error:land_war.annex_region(1,{'occupation_id':row.id})
        self.assertIn('wszystkimi bazami i miastami',str(error.exception))
        self.player=2
        # Retaking the last object ends the region occupation; the base is usable at once, its garrison limited by capacity.
        army=self.recapture(reserve,'base',self.enemy.id,20000)
        self.assertEqual((army.battle['result'],army.status),('ATTACKER_WON','MERGED'))
        db.session.expire_all()
        self.assertEqual(db.session.get(Occupation,row.id).status,'ENDED')
        base=db.session.get(MilitaryBase,self.enemy.id)
        self.assertEqual(base.garrison['soldiers'],10000,'level 1 land base holds 10 000 soldiers; the rest returns to the pool')
        from sqlalchemy.orm import Session
        with Session(db.engine) as session:
            land_war.require_usable_base(session,base.id)
            land_war.require_buildable(session,2,2)

    def test_second_wave_does_not_fight_own_troops_after_recapture(self):
        row,reserve=self.recapture_setup()
        with patch('game.road_projects.neighboring_countries',return_value=set()):
            first=land_war.launch_invasion(2,{'source_base_id':reserve.id,'target_kind':'city','target_id':10,'soldiers':20000,'request_id':key()})
            second=land_war.launch_invasion(2,{'source_base_id':reserve.id,'target_kind':'city','target_id':10,'soldiers':300,'request_id':key()})
        db.session.expire_all();before=db.session.get(MilitaryBase,reserve.id).garrison['soldiers']
        self.assertEqual(before,45000-20000-300)
        # Obie fale docierają jednocześnie: pierwsza odbija miasto, druga wraca do bazy bez bitwy z własnymi wojskami.
        self.assertEqual(self.arrive(first,[0.0,0.0]).battle['result'],'ATTACKER_WON')
        army=self.army(second)
        self.assertEqual((army.battle['result'],army.status),('TARGET_GONE','WITHDRAWN'))
        db.session.expire_all()
        self.assertEqual(db.session.get(MilitaryBase,reserve.id).garrison['soldiers'],before+300)  # żołnierze wrócili, nikt nie zginął

    def city_occupation(self):
        return db.session.scalar(select(Occupation).where(Occupation.kind=='city',Occupation.status=='ACTIVE'))

    def test_occupier_withdraws_part_of_the_troops_to_own_base(self):
        self.conquer_region();city=self.city_occupation()
        db.session.expire_all();before=db.session.get(MilitaryBase,self.home.id).garrison['soldiers']
        result=land_war.withdraw_occupation(1,{'occupation_id':city.id,'base_id':self.home.id,'soldiers':10})
        self.assertFalse(result['ended'])
        db.session.expire_all()
        self.assertEqual(db.session.get(MilitaryBase,self.home.id).garrison['soldiers'],before+10)
        self.assertEqual(db.session.get(Occupation,city.id).status,'ACTIVE')
        army=db.session.scalar(select(LandArmy).where(LandArmy.target_kind=='city',LandArmy.status=='OCCUPYING'))
        self.assertEqual(army.soldiers,100-10)

    def test_reinforcements_march_to_occupied_city_and_join_the_occupation(self):
        self.conquer_region();city=self.city_occupation()
        db.session.expire_all();before=db.session.get(MilitaryBase,self.home.id).garrison['soldiers']
        id=self.invade('city',10,soldiers=50,armored=2,reinforce=True)
        army=self.army(id)
        self.assertEqual((army.status,army.role,army.target_country_id),('MARCHING','invasion',2))   # marsz po terytorium właściciela
        db.session.expire_all();self.assertEqual(db.session.get(MilitaryBase,self.home.id).garrison['soldiers'],before-50)
        army=self.arrive(id,[])
        self.assertEqual((army.status,army.battle['result']),('OCCUPYING','REINFORCED'))
        self.assertEqual(db.session.get(Occupation,city.id).status,'ACTIVE')
        present=land_war.withdraw_occupation(1,{'occupation_id':city.id,'base_id':self.home.id,'soldiers':150,'armored':2})
        self.assertTrue(present['ended'])                           # 100 okupantów + 50 posiłków, wycofane razem
        self.assertTrue(any('Posiłki dotarły' in (n.system_text or '') for n in db.session.query(GameNotification)))

    def test_reinforcements_require_own_occupation_and_fight_after_recapture(self):
        with self.assertRaisesRegex(FinanceError,'okupowanej przez nasze'):self.invade('city',10,soldiers=10,reinforce=True)
        self.conquer_region();city=self.city_occupation()
        id=self.invade('city',10,soldiers=1000,reinforce=True)
        # Przed dotarciem posiłków właściciel odbija miasto — posiłki walczą o nie jak przy inwazji.
        db.session.get(Occupation,city.id).status='ENDED';db.session.commit()
        army=self.arrive(id,[0.0,0.0])
        self.assertIn(army.battle['result'],('ATTACKER_WON','DEFENDER_WON'))

    def test_full_withdrawal_ends_object_and_region_occupation(self):
        row=self.conquer_region();city=self.city_occupation()
        land_war.decide_region(1,{'occupation_id':row.id,'occupy':True})
        result=land_war.withdraw_occupation(1,{'occupation_id':city.id,'base_id':self.home.id,'soldiers':100})
        self.assertTrue(result['ended'])
        db.session.expire_all()
        self.assertEqual(db.session.get(Occupation,city.id).status,'ENDED')
        self.assertEqual(db.session.get(Occupation,row.id).status,'ACTIVE')     # baza regionu wciąż zajęta — region nadal okupowany
        base=db.session.scalar(select(Occupation).where(Occupation.kind=='base',Occupation.status=='ACTIVE'))
        soldiers=db.session.scalar(select(LandArmy.soldiers).where(LandArmy.target_kind=='base',LandArmy.status=='OCCUPYING'))
        land_war.withdraw_occupation(1,{'occupation_id':base.id,'base_id':self.home.id,'soldiers':soldiers})
        db.session.expire_all()
        self.assertEqual(db.session.get(Occupation,row.id).status,'ENDED')       # wycofanie ze wszystkich obiektów kończy okupację regionu
        self.assertTrue(any('wycofał wszystkie wojska' in (n.system_text or '') for n in db.session.query(GameNotification)))

    def test_withdrawal_limited_by_base_capacity_and_present_units(self):
        self.conquer_region();city=self.city_occupation()
        small=MilitaryBase(panstwo_id=1,region_id=1,kind='air',level=1,garrison={'soldiers':9995,'fighters':1},map_x=5,map_y=5);db.session.add(small);db.session.commit()
        with self.assertRaisesRegex(FinanceError,'nie pomieści'):land_war.withdraw_occupation(1,{'occupation_id':city.id,'base_id':small.id,'soldiers':10})
        self.assertEqual(land_war.free_capacity(small),{'soldiers':5,'armored':0,'tanks':0})
        land_war.withdraw_occupation(1,{'occupation_id':city.id,'base_id':small.id,'soldiers':5})
        with self.assertRaisesRegex(FinanceError,'tylko'):land_war.withdraw_occupation(1,{'occupation_id':city.id,'base_id':self.home.id,'soldiers':1000})
        self.player=2
        with self.assertRaises(FinanceError):land_war.withdraw_occupation(2,{'occupation_id':city.id,'base_id':self.enemy.id,'soldiers':1})

    def test_land_battles_become_public_events_and_recapture_is_recognised(self):
        from types import SimpleNamespace
        from datetime import datetime as dt
        from game.autonomy_models import AutonomyEvent,AutonomySourceReceipt
        from game import autonomy_memory
        from game.military_models import MilitaryFlight
        from game.intelligence_models import IntelligenceMission
        from game.diplomacy_models import DiplomaticAction
        for model in (AutonomyEvent,AutonomySourceReceipt,MilitaryFlight,IntelligenceMission,DiplomaticAction):model.__table__.create(db.engine,checkfirst=True)
        row,reserve=self.recapture_setup()
        self.recapture(reserve,'city',10,20000)
        from sqlalchemy.orm import Session
        with Session(db.engine) as session,session.begin():autonomy_memory.ingest_sources(session,SimpleNamespace(started_at=dt(1,1,1)),self.now)
        kinds=sorted((e.kind,e.actor_id,e.target_id,e.payload['won']) for e in db.session.scalars(select(AutonomyEvent)))
        self.assertIn(('RECAPTURE_ATTACK',2,1,True),kinds)
        self.assertIn(('LAND_ATTACK',1,2,True),kinds)
        self.assertTrue(all(e.public for e in db.session.scalars(select(AutonomyEvent))))

    def test_partial_recapture_keeps_region_and_frees_the_base(self):
        row,reserve=self.recapture_setup()
        army=self.recapture(reserve,'base',self.enemy.id,5000)
        self.assertEqual(army.status,'MERGED')
        db.session.expire_all()
        self.assertEqual(db.session.get(Occupation,row.id).status,'ACTIVE')
        from sqlalchemy.orm import Session
        with Session(db.engine) as session:
            land_war.require_usable_base(session,self.enemy.id)
            with self.assertRaises(FinanceError):land_war.require_buildable(session,2,2)

    def test_pending_decision_lapses_after_any_recapture(self):
        row=self.conquer_region()
        land_war.decide_region(1,{'occupation_id':row.id,'occupy':False})
        from sqlalchemy import text
        db.session.execute(text("INSERT INTO game_state_budgets (id,panstwo_id,game_year,period) VALUES (2,2,2990,1)"))
        db.session.execute(text("INSERT INTO game_state_budget_allocations (id,budget_id,category_code,amount) VALUES (2,2,'armed_forces',1000000000000)"))
        reserve=MilitaryBase(panstwo_id=2,region_id=3,kind='land',level=7,garrison={'soldiers':45000,'armored':0,'tanks':0},map_x=200,map_y=0);db.session.add(reserve);db.session.commit()
        self.player=2;self.recapture(reserve,'city',10,20000)
        db.session.expire_all();self.assertEqual(db.session.get(Occupation,row.id).status,'ENDED')

    def test_recapture_requires_war(self):
        row,reserve=self.recapture_setup()
        db.session.query(Stosunki).delete();db.session.commit()
        with self.assertRaises(FinanceError) as error:self.recapture(reserve,'city',10,100)
        self.assertIn('wojna',str(error.exception))


class SovereigntyTests(LandWarFixture):
    def annex_capital(self):
        from game.industry_models import PowerPlant
        from game.commerce_models import ResourceStock
        db.session.get(Miasto,10).miasto_typ_id=1
        db.session.add(Miasto(miasto_id=12,panstwo_id=2,miasto_nazwa='Miasto C',region_id=3,czy_na_mapie='TAK',miasto_populacja=10))
        far=MilitaryBase(panstwo_id=2,region_id=3,kind='land',level=1,garrison={'soldiers':700,'armored':0,'tanks':0},map_x=300,map_y=0)
        db.session.add_all([far,PowerPlant(panstwo_id=2,region_id=3,map_x=1,map_y=1,level=1,kind='coal',investment=0,created_game_at=NOW,checked_at=NOW,air_filter=False,pollution_points=0),
                            ResourceStock(panstwo_id=2,resource='coal',quantity=40),ResourceStock(panstwo_id=1,resource='coal',quantity=2)])
        db.session.commit();self.far=far.id
        self.arrive(self.invade(soldiers=3000),[0.0,0.0])
        self.arrive(self.invade('city',10,soldiers=100),[0.0,0.0])
        row=db.session.scalar(select(Occupation).where(Occupation.kind=='region'))
        land_war.decide_region(1,{'occupation_id':row.id,'occupy':True})
        db.session.expire_all();row=db.session.get(Occupation,row.id)
        self.now=row.started_at+timedelta(days=30)
        land_war.annex_region(1,{'occupation_id':row.id})
        db.session.expire_all()
        return row

    def test_capital_annexation_transfers_the_whole_country(self):
        from game.land_war_models import SovereigntyLoss
        from game.industry_models import PowerPlant
        from game.commerce_models import ResourceStock
        before=db.session.query(Wojsko).filter_by(panstwo_id=1).one().wojska_ladowe_ilosc
        self.annex_capital()
        loss=db.session.get(SovereigntyLoss,2)
        self.assertEqual((loss.annexed_by,loss.capital_region_id),(1,2))
        self.assertEqual({r.panstwo_id for r in db.session.query(Region).filter(Region.region_id.in_([2,3]))},{1})
        self.assertEqual({c.panstwo_id for c in db.session.query(Miasto).filter(Miasto.miasto_id.in_([10,12]))},{1})
        self.assertEqual(db.session.get(MilitaryBase,self.far).panstwo_id,1)
        self.assertEqual(db.session.query(PowerPlant).one().panstwo_id,1)
        self.assertEqual(db.session.get(ResourceStock,(1,'coal')).quantity,42)
        old=db.session.query(Wojsko).filter_by(panstwo_id=2).one();new=db.session.query(Wojsko).filter_by(panstwo_id=1).one()
        self.assertEqual((old.wojska_ladowe_ilosc,old.czolgi_ilosc,old.liczba_baz_ladowych),(0,0,0))
        self.assertGreater(new.wojska_ladowe_ilosc,before+40000,'the defeated army joins the annexer')
        self.assertEqual(new.wyszkolenie_ladowe,300,'the annexer keeps its own training')
        self.assertTrue(any('utraciło suwerenność' in (n.system_text or '') for n in db.session.query(GameNotification)))
        # 21 Nov 2026: region 2 nie ma innej stolicy regionu — dawna stolica państwa zostaje stolicą regionu
        self.assertEqual(db.session.get(Miasto,10).miasto_typ_id,2)
        self.assertEqual(loss.transferred['capitals'],{'10':2})

    def test_capital_becomes_city_when_region_has_regional_capital(self):
        from game.sovereignty import demote_capitals
        db.session.get(Miasto,10).miasto_typ_id=1
        db.session.add(Miasto(miasto_id=13,panstwo_id=2,miasto_nazwa='Stolica regionu',region_id=2,czy_na_mapie='TAK',miasto_populacja=5,miasto_typ_id=2))
        db.session.commit()
        self.assertEqual(demote_capitals(db.session,2),{10:3})
        self.assertEqual((db.session.get(Miasto,10).miasto_typ_id,db.session.get(Miasto,13).miasto_typ_id),(3,2))

    def test_capital_annexation_moves_the_whole_gdp(self):
        from sqlalchemy import update
        db.session.execute(update(Panstwo).where(Panstwo.PANSTWO_ID==2).values(panstwo_PKB=10000000,panstwo_populacja=10000));db.session.commit()
        self.annex_capital()
        stats=lambda id:db.session.execute(select(Panstwo.panstwo_PKB,Panstwo.panstwo_populacja,Panstwo.panstwo_powierzchnia).where(Panstwo.PANSTWO_ID==id)).one()
        winner,loser=stats(1),stats(2)
        self.assertEqual(winner.panstwo_PKB,1000000000000+10000000,'the annexer takes the whole GDP of an absorbed country')
        self.assertEqual((loser.panstwo_PKB,loser.panstwo_populacja),(0,0))
        self.assertEqual(winner.panstwo_populacja,sum(r.region_populacja for r in db.session.query(Region).filter_by(panstwo_id=1)))
        from models import PKBStateHistory
        history={(h.panstwo_id,h.old_pkb,h.new_pkb,h.change_delta) for h in db.session.query(PKBStateHistory).filter_by(source='ANEKSJA')}
        self.assertEqual(history,{(1,1000000000000,1000010000000,10000000),(2,10000000,0,-10000000)})

    def test_lost_country_cannot_act_but_keeps_forum_and_messages(self):
        self.annex_capital()
        from game import sovereignty
        from game.finance_service import FinancePermissionError
        from sqlalchemy.orm import Session
        with Session(db.engine) as session:
            with self.assertRaises(FinancePermissionError) as error:sovereignty.require_sovereign(session,2)
            self.assertIn('Twoja historia się skończyła',str(error.exception))
            sovereignty.require_sovereign(session,1)
        from game.models import GameUser,GamePlayerCountry
        db.session.query(GamePlayerCountry).filter(GamePlayerCountry.panstwo_id.in_([1,2])).delete()
        db.session.add_all([GameUser(id=99,username='pokonany',username_normalized='pokonany',is_active=True),GameUser(id=98,username='zwyciezca',username_normalized='zwyciezca',is_active=True)]);db.session.flush()
        db.session.add_all([GamePlayerCountry(user_id=99,panstwo_id=2),GamePlayerCountry(user_id=98,panstwo_id=1)]);db.session.commit()
        app=self.app
        from flask import Blueprint
        sovereignty.register(app)
        for name,prefix,endpoint in (('game_forum','/game/forum','page'),('game_messages','/game/wiadomosci','index')):
            if name not in app.blueprints:
                bp=Blueprint(name,__name__,url_prefix=prefix);bp.add_url_rule('/',endpoint,lambda name=name:name);app.register_blueprint(bp)
        app.add_url_rule('/game/test-panel','test_panel',lambda:'panel');app.add_url_rule('/game/test-akcja','test_action',lambda:'ok',methods=['POST'])
        client=app.test_client()
        with client.session_transaction() as web:web['game_user_id']=99
        with app.test_request_context():
            from flask import url_for
            forum_url=url_for('game_forum.page')
        self.assertNotIn(client.get(forum_url,headers={'Accept':'text/html'}).status_code,(303,403),'forum stays available')
        page=client.get('/game/test-panel',headers={'Accept':'text/html'});self.assertEqual(page.status_code,303);self.assertIn('/game/forum',page.headers['Location'])
        action=client.post('/game/test-akcja');self.assertEqual(action.status_code,403);self.assertIn('suwerenność',action.get_json()['error'])
        with client.session_transaction() as web:web['game_user_id']=98
        self.assertEqual(client.get('/game/test-panel').data,b'panel')

    def test_banner_in_layouts(self):
        from pathlib import Path
        root=Path(__file__).resolve().parents[1]/'templates'
        for name in ('game/game_base_layout.html','base_layout.html'):
            self.assertIn("{% include '_sovereignty_banner.html' %}",(root/name).read_text(),name)
        self.assertIn('game_sovereignty_lost',(root/'_sovereignty_banner.html').read_text())


class InterfaceTests(LandWarFixture):
    def test_war_page_carries_land_war_config_and_state(self):
        with patch('game.military.land_targets',return_value=[2]):
            response=self.client.get('/game/panel-wojenny')
        self.assertEqual(response.status_code,200)
        text=response.get_data(as_text=True)
        for needle in ('"landWar"','INWAZJA.svg','MIASTO.svg','game_land_war.js','land-war-occupations'):self.assertIn(needle,text)
        self.invade(soldiers=10)
        state=self.client.get('/game/panel-wojenny/stan').get_json()
        self.assertEqual(state['armies'][0]['status'],'MARCHING');self.assertEqual(state['armies'][0]['speedKmh'],50)
        self.assertEqual(self.client.post('/game/panel-wojenny/armia-ladowa',json={}).status_code,403)

    def test_occupied_region_red_grid_and_city_base_filter(self):
        from pathlib import Path
        script=(Path(__file__).resolve().parents[1]/'static/js/game_land_war.js').read_text()
        for text in ('land-occupation-hatch',"'#c62828'",'rotate(45)',"fillColor:'url(#land-occupation-hatch)'",'String(base.regionId)===String(city.regionId)','do zabrania:'):self.assertIn(text,script)

    def test_front_end_texts(self):
        from pathlib import Path
        script=(Path(__file__).resolve().parents[1]/'static/js/game_land_war.js').read_text()
        for text in ('Dodaj obronę wojska','Wprowadź armię lądową','Okupowane przez:','Okupowany przez:','#d32f2f',"dashArray:'8 8'",'Prędkość:','Anektuj region','Czy prowadzić okupację regionu?',
                     "'Dorzuć wojsko'",'reinforce:true','Do aneksji:','regionUnderOccupation'):
            self.assertIn(text,script)


class RecaptureInterfaceTests(LandWarFixture):
    def test_recapture_buttons_and_locked_build_buttons(self):
        from pathlib import Path
        root=Path(__file__).resolve().parents[1]/'static/js'
        land=(root/'game_land_war.js').read_text();military=(root/'game_military.js').read_text()
        for text in ("'Odbij miasto'","'Odbij bazę'",'bindBase','regionOccupied','Odbicie wymaga trwającej wojny z okupantem.'):self.assertIn(text,land)
        self.assertIn('GameLandWar?.bindBase(baseMarker,base,tooltip)',military)
        self.assertIn('GameLandWar?.regionUnderOccupation?.(id)?DEF.occupiedHover:DEF.hover',military)
        self.assertIn('baseKindBadge(base,symbol)',military)
        self.assertIn("lockButton(button('Dodaj obronę przeciwrakietową'",military)
        self.assertIn('lockButton(actions.lastElementChild)',military)


class TrainingPurchaseTests(LandWarFixture):
    def buy(self,branch,levels,request_id=None):
        from game.military_training import train
        return train(1,{'branch':branch,'levels':levels,'request_id':request_id or key()})
    def test_prices_budget_limit_and_idempotency(self):
        from game.land_war_models import TrainingExpense
        from game.military_service import military_budget
        _,_,before=military_budget(db.session,1)
        request=key()
        self.assertEqual(self.buy('land',2,request),302);self.assertEqual(self.buy('land',2,request),302,'the same request is not charged twice')
        self.assertEqual(self.buy('naval',1),101);self.assertEqual(self.buy('air',1),101)
        amounts={row.branch:row.amount for row in db.session.query(TrainingExpense)}
        self.assertEqual(amounts,{'land':Decimal('3000000000'),'naval':Decimal('1700000000'),'air':Decimal('1900000000')})
        _,_,after=military_budget(db.session,1);self.assertEqual(before-after,Decimal('6600000000'))
        with self.assertRaises(FinanceError) as error:self.buy('land',699)
        self.assertIn('1000',str(error.exception))
        self.set_budget(1000)
        with self.assertRaises(FinanceError) as error:self.buy('air',1)
        self.assertIn('budżecie sił zbrojnych',str(error.exception))
    def test_army_page_buttons_and_route(self):
        response=self.client.get('/game/sily-zbrojne');text=response.get_data(as_text=True)
        self.assertEqual(response.status_code,200)
        for branch in ('land','naval','air'):self.assertIn(f'data-train="{branch}"',text)
        self.assertIn('army-training-minus',text);self.assertIn('army-training-plus',text);self.assertIn('game_army_training.js',text)
        self.assertEqual(self.client.post('/game/sily-zbrojne/wyszkol',json={'branch':'land','levels':1,'request_id':key()}).status_code,403)
        with self.client.session_transaction() as browser:browser['game_csrf_token']='token'
        response=self.client.post('/game/sily-zbrojne/wyszkol',json={'branch':'land','levels':1,'request_id':key()},headers={'X-CSRF-Token':'token'})
        self.assertEqual(response.get_json()['level'],301)



class OccupiedRegionBuildTests(LandWarFixture):
    def occupy_region_2(self):
        db.session.add(Occupation(kind='region',region_id=2,owner_id=2,occupier_id=1,status='ACTIVE',started_at=NOW));db.session.commit()
    def test_owner_cannot_build_in_an_occupied_region(self):
        self.occupy_region_2();self.player=2
        from game.infrastructure_service import start_project
        with self.assertRaises(FinanceError) as error:start_project(2,2,'road',1,False)
        self.assertIn('okupowany',str(error.exception))
        with patch('game.military_service._country_for_user',return_value=SimpleNamespace(PANSTWO_ID=2)),self.assertRaises(FinanceError) as error:
            from game.military_service import change_defense
            change_defense(2,'place',{'kind':'land','region_id':2,'count':1})
        self.assertIn('okupowany',str(error.exception))
    def test_guard_allows_other_regions_and_the_occupier(self):
        self.occupy_region_2()
        from sqlalchemy.orm import Session
        with Session(db.engine) as session:
            land_war.require_buildable(session,3,2)
            land_war.require_buildable(session,2,1)
            with self.assertRaises(FinanceError):land_war.require_buildable(session,2,2)
    def test_every_build_path_checks_the_occupation(self):
        from pathlib import Path
        root=Path(__file__).resolve().parents[1]/'game'
        for name in ('industry_service.py','mining_service.py','infrastructure_service.py','missile_defense.py','roads.py','military_service.py'):
            self.assertIn('require_buildable',(root/name).read_text(),name)


class BaseLiquidationTests(LandWarFixture):
    def liquidate(self,base_id,country=1):
        from game.military_service import change_defense
        with patch('game.military_service._country_for_user',return_value=SimpleNamespace(PANSTWO_ID=country)):change_defense(1,'liquidate',{'base_id':base_id})
        db.session.expire_all()
    def test_liquidation_returns_garrison_and_reduces_base_count(self):
        from game.military_models import MissileDefense
        db.session.add(MissileDefense(panstwo_id=1,region_id=1,target_kind='base',target_id=self.home.id,level=1,ammunition=10));db.session.commit()
        before=db.session.query(Wojsko).filter_by(panstwo_id=1).one()
        totals=(before.liczba_baz_ladowych,before.wojska_ladowe_ilosc,before.czolgi_ilosc)
        home_id=self.home.id;self.liquidate(home_id)
        self.assertIsNone(db.session.get(MilitaryBase,home_id))
        after=db.session.query(Wojsko).filter_by(panstwo_id=1).one()
        self.assertEqual((after.liczba_baz_ladowych,after.wojska_ladowe_ilosc,after.czolgi_ilosc),(totals[0]-1,totals[1],totals[2]),'troops return to the pool, only the base is gone')
        self.assertEqual(db.session.query(MissileDefense).count(),0)
    def test_blocked_with_city_defenders_or_when_occupied(self):
        id=land_war.add_city_defense(1,{'city_id':11,'base_id':self.home.id,'soldiers':10,'request_id':key()})
        with self.assertRaises(FinanceError) as error:self.liquidate(self.home.id)
        self.assertIn('wycofaj',str(error.exception))
        land_war.withdraw_city_defense(1,{'army_id':id});self.liquidate(self.home.id)
        db.session.add(Occupation(kind='base',base_id=self.enemy.id,region_id=2,owner_id=2,occupier_id=1,status='ACTIVE',started_at=NOW));db.session.commit()
        with self.assertRaises(FinanceError):self.liquidate(self.enemy.id,country=2)
    def test_button_in_base_panel(self):
        from pathlib import Path
        script=(Path(__file__).resolve().parents[1]/'static/js/game_military.js').read_text()
        self.assertIn("Zlikwiduj bazę",script);self.assertIn("action:'liquidate'",script)
