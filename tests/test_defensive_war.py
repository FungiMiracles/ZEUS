"""17 Nov 2026: pokój kończy okupację, przesunięcia do sił zbrojnych w wojnie obronnej, szkolenie PAGA2 w czasie wojny."""
import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from sqlalchemy import select
from sqlalchemy.orm import Session,lazyload
from extensions import db
from models import Stosunki
from test_land_war import LandWarFixture
from game.military_models import MilitaryBase
from game.land_war_models import LandArmy, Occupation
from game.forum_models import GameNotification
from game import land_war


class PeaceEndsOccupationTests(LandWarFixture):
    def conquer_region(self):
        self.arrive(self.invade(soldiers=3000),[0.0,0.0])
        self.arrive(self.invade('city',10,soldiers=100),[0.0,0.0])
        region=db.session.scalar(select(Occupation).where(Occupation.kind=='region'))
        land_war.decide_region(1,{'occupation_id':region.id,'occupy':True})
        return region

    def make_peace(self):
        from game.diplomacy_service import apply_change,dictionaries
        with Session(db.engine) as session,session.begin():
            _,states,neutral=dictionaries(session)
            row=session.scalar(select(Stosunki).options(lazyload('*')).where(Stosunki.PANSTWO_ID==1,Stosunki.PANSTWO_ID2==2))
            apply_change(session,row,1,2,neutral,states['pokoj'],self.now)
        db.session.expire_all()

    def test_peace_ends_object_and_region_occupations_and_returns_troops(self):
        region=self.conquer_region()
        before=db.session.get(MilitaryBase,self.home.id).garrison['soldiers']
        occupying=sum(a.soldiers for a in db.session.scalars(select(LandArmy).where(LandArmy.status=='OCCUPYING')))
        self.assertGreater(occupying,0)
        self.make_peace()
        self.assertEqual(db.session.scalar(select(Occupation.id).where(Occupation.status.in_(['ACTIVE','PENDING']))),None)
        self.assertEqual(db.session.get(Occupation,region.id).status,'ENDED')
        self.assertEqual(db.session.scalar(select(LandArmy.id).where(LandArmy.status=='OCCUPYING')),None)
        self.assertEqual(db.session.get(MilitaryBase,self.home.id).garrison['soldiers'],before+occupying)
        texts=[n.system_text or '' for n in db.session.query(GameNotification)]
        self.assertTrue(any('zakończyło okupację naszego terytorium' in t for t in texts))
        self.assertTrue(any('Wojska okupacyjne wróciły do baz' in t for t in texts))

    def test_marching_army_turns_back_on_peace(self):
        self.invade(soldiers=50)
        db.session.expire_all()
        army=db.session.scalar(select(LandArmy).where(LandArmy.status=='MARCHING'))
        self.assertIsNotNone(army)
        self.make_peace()
        self.assertEqual(db.session.get(LandArmy,army.id).status,'WITHDRAWN')


class DefensiveWarTransferTests(LandWarFixture):
    def test_defensive_war_detected_only_with_enemy_on_territory_and_war(self):
        from game.budget_transfers import defensive_war
        self.assertFalse(defensive_war(db.session,2))
        self.arrive(self.invade(soldiers=3000),[0.0,0.0])     # państwo 1 okupuje bazę państwa 2
        self.assertTrue(defensive_war(db.session,2))
        self.assertFalse(defensive_war(db.session,1))
        row=db.session.scalar(select(Stosunki).options(lazyload('*')).where(Stosunki.PANSTWO_ID==1,Stosunki.PANSTWO_ID2==2));row.stan_id=2;db.session.commit()   # zawieszenie broni
        self.assertFalse(defensive_war(db.session,2))

    def test_transfers_never_need_trust(self):
        # 21 Nov 2026: próg zaufania do władzy dla przesunięć między sektorami zniesiony (także poza wojną obronną)
        from game import budget_transfers
        cases=[(True,'healthcare','armed_forces'),(True,'healthcare','education'),(False,'healthcare','armed_forces'),
               (False,'reserve','education'),(True,'armed_forces','healthcare')]
        for defensive,source,destination in cases:
            with patch.object(budget_transfers,'defensive_war',return_value=defensive):
                self.assertFalse(budget_transfers.transfer_needs_trust(db.session,2,source,destination),(defensive,source,destination))


class Paga2WarTrainingTests(LandWarFixture):
    def test_war_prioritises_land_training_with_higher_weight(self):
        from game.paga2.defense import training_options
        forces=SimpleNamespace(has_budget=True,army={'wyszkolenie_ladowe':150,'wyszkolenie_morskie':100,'wyszkolenie_powietrzne':100},budget_available=20e9)
        war=SimpleNamespace(traits={},situation={'level':'war'},limits={'per_action':.43})
        peace=SimpleNamespace(traits={'militarism':80},situation={'level':'peace'},limits={'per_action':.43})
        option=training_options(war,forces)[0]
        self.assertEqual(option.payload['branch'],'land')
        self.assertEqual(option.payload['levels'],int(.9*.43*20e9//1.5e9))
        self.assertGreater(option.base,training_options(peace,forces)[0].base)
        self.assertEqual(training_options(peace,forces)[0].payload['branch'],'naval')


class Paga2CeasefireLengthTests(LandWarFixture):
    def test_ceasefire_length_within_limits_and_follows_traits(self):
        from game.paga2 import diplomacy
        with patch.object(diplomacy,'weakness',return_value=0.0):
            calm=SimpleNamespace(traits={'agreeableness':90,'strategic_patience':90,'revenge':10,'militarism':10},situation={})
            hawk=SimpleNamespace(traits={'agreeableness':5,'strategic_patience':5,'revenge':95,'militarism':95},situation={})
            long,short=diplomacy.ceasefire_length(calm,2),diplomacy.ceasefire_length(hawk,2)
        self.assertGreater(long,short)
        for days in (long,short):self.assertTrue(1<=days<=180)
