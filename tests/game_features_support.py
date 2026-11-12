"""Izolowane środowisko testów poczty i zdarzeń, bez schedulerów i MySQL."""
import unittest
from pathlib import Path

from flask import Flask
from sqlalchemy import event, select, func

from extensions import db
from game.industry_models import PowerPlant,IndustryClock,IndustryMovement
from game.research_models import AmmunitionFactory
from game.infrastructure_models import InfrastructureProject
from game.military_models import MilitaryBase, MilitaryExpense, MilitaryMaintenance, MilitaryOrder, MilitaryFlight, MapCalibration, MilitaryVessel, MissileDefense, MissileDefenseExpense
from game.communication import messages_bp
from game.communication_models import PrivateMessage
from game.diplomacy import diplomacy_bp
from game.diplomacy_models import DiplomaticAction
from game.event_models import GeneratedEventSnapshot
from game.forum import forum_bp
from game.forum_models import ForumMessage, GameNotification
from game.models import GameUser, GamePlayerCountry
from game.srodowisko import environment_bp
from models import (Panstwo, Region, Stosunki, AudytStosunki, DictStosunkiRelacja,
                    DictStosunkiStan, Zdarzenie, RegionStateHistory, SpoleczenstwoStateHistory)


class FeatureTestCase(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.app = Flask(__name__, template_folder=str(root / 'templates'), static_folder=str(root / 'static'))
        self.app.config.update(TESTING=True, SECRET_KEY='features-test-only', SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        db.init_app(self.app)
        from routes_region_secession import region_sovereignty_bp
        self.app.register_blueprint(region_sovereignty_bp)
        from game.commerce import trade_bp
        for blueprint in [messages_bp, diplomacy_bp, forum_bp, environment_bp, trade_bp]:
            self.app.register_blueprint(blueprint)
        for name in ['wejscie', 'game_main_page', 'game_logout', 'game_demography.page']:
            self.app.add_url_rule('/test/' + name, name, lambda: '')
        self.app.add_template_filter(str, 'spacenum')
        self.app.add_template_filter(str, 'game_money')
        self.ctx = self.app.app_context()
        self.ctx.push()
        @event.listens_for(db.engine, 'connect')
        def sqlite_functions(connection, record):
            connection.create_function('CHAR_LENGTH', 1, len)
        db.metadata.create_all(db.engine, tables=[model.__table__ for model in [
            Panstwo, Region, GameUser, GamePlayerCountry, Stosunki, AudytStosunki,
            DictStosunkiRelacja, DictStosunkiStan, DiplomaticAction, ForumMessage,
            GameNotification, GeneratedEventSnapshot, PrivateMessage, Zdarzenie,
            RegionStateHistory, SpoleczenstwoStateHistory,
        ]])
        InfrastructureProject.__table__.create(db.engine, checkfirst=True)
        for model in (MilitaryBase, MilitaryExpense, MilitaryMaintenance, MilitaryOrder, MilitaryFlight, MapCalibration, MilitaryVessel, MissileDefense, MissileDefenseExpense):
            model.__table__.create(db.engine, checkfirst=True)
        # Land armies and occupations (11 Nov 2026) are part of military counts and armed-forces spending.
        from game.land_war_models import LandArmy, Occupation, TrainingExpense, SovereigntyLoss
        from game.radar_models import Radar, RadarExpense, RadarDetection
        for model in (LandArmy, Occupation, TrainingExpense, SovereigntyLoss, Radar, RadarExpense, RadarDetection):
            model.__table__.create(db.engine, checkfirst=True)
        from sqlalchemy import MetaData, Table, Column, String
        from game.finance_models import StateBudget, StateBudgetAllocation, StateFinancialAccount
        metadata = MetaData()
        for model in (StateBudget, StateBudgetAllocation, StateFinancialAccount):
            Table(model.__tablename__, metadata, *[Column(c.name, String(c.type.length) if isinstance(c.type, String) else c.type, primary_key=c.primary_key, nullable=True) for c in model.__table__.columns]).create(db.engine, checkfirst=True)
        from game.civic_models import Road,RoadInvestment,RoadProposal,TreasuryAdjustment,CountryTaxPolicy
        for model in (Road,RoadInvestment,RoadProposal,TreasuryAdjustment,CountryTaxPolicy):model.__table__.create(db.engine,checkfirst=True)
        from game.research_models import ResearchAccount,ResearchExpense,ResearchInvestment,AmmunitionFactory
        for model in (ResearchAccount,ResearchExpense,ResearchInvestment,AmmunitionFactory):model.__table__.create(db.engine,checkfirst=True)
        from game.industry_models import PowerPlant,IndustryClock,IndustryMovement
        for model in (PowerPlant,IndustryClock,IndustryMovement):model.__table__.create(db.engine,checkfirst=True)
        from game.population_structure import PopulationStructure
        PopulationStructure.__table__.create(db.engine,checkfirst=True)
        from game.loan_models import StateLoan,LoanMovement
        for model in (StateLoan,LoanMovement):model.__table__.create(db.engine,checkfirst=True)
        from game.social_benefits import BenefitPayment,BenefitSettlement,MissedBenefitPeriod
        for model in (BenefitPayment,BenefitSettlement,MissedBenefitPeriod):model.__table__.create(db.engine,checkfirst=True)
        from game.finance_models import BudgetTransfer
        BudgetTransfer.__table__.create(db.engine)
        from game.intelligence_models import IntelligenceAgent,CounterIntelligence,IntelligenceMission,IntelligenceExpense
        for model in (IntelligenceAgent,CounterIntelligence,IntelligenceMission,IntelligenceExpense):model.__table__.create(db.engine)
        from game.commerce_models import ResourceStock,Mine,MiningExpense,PortTariff,TradeOffer,TradeShipment,TradeReserveMovement
        for model in (ResourceStock,Mine,MiningExpense,PortTariff,TradeOffer,TradeShipment,TradeReserveMovement):model.__table__.create(db.engine)
        db.session.add(MapCalibration(id=1,reference_city_a=1,reference_city_b=852,reference_km=100,km_per_unit=1,reference_a_x=0,reference_a_y=0,reference_b_x=100,reference_b_y=0))
        db.session.add_all([
            *[Panstwo(PANSTWO_ID=i, panstwo_nazwa=f'Państwo {i}') for i in range(1, 5)],
            *[GameUser(id=i, username=f'Gracz{i}', username_normalized=f'gracz{i}',
                       email=f'{i}@test', email_normalized=f'{i}@test', password_hash='test') for i in range(1, 5)],
            *[GamePlayerCountry(user_id=i, panstwo_id=i) for i in range(1, 4)],
            Region(region_id=1, panstwo_id=1, region_nazwa='Pierwszy region'),
            Region(region_id=2, panstwo_id=2, region_nazwa='Drugi region'),
            DictStosunkiRelacja(relacja_id=6, relacja_nazwa='Neutralne'),
            DictStosunkiRelacja(relacja_id=10, relacja_nazwa='Wrogie'),
            DictStosunkiStan(stan_id=1, stan_nazwa='Pokój'),
            DictStosunkiStan(stan_id=8, stan_nazwa='Wojna kinetyczna'),
            DictStosunkiStan(stan_id=2, stan_nazwa='Zawieszenie broni'),
        ])
        db.session.commit()
        self.client = self.app.test_client()
        self.login(1)

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.ctx.pop()

    def login(self, user_id):
        with self.client.session_transaction() as browser:
            browser['game_user_id'] = user_id
            browser['game_csrf_token'] = 'token'

    def post(self, path, **data):
        return self.client.post(path, data={'csrf_token': 'token', **data}, headers={'Accept': 'application/json'})

    def count(self, model):
        return db.session.scalar(select(func.count()).select_from(model))
