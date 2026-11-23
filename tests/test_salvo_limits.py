"""23 Nov 2026: limity salwy (myśliwiec 10 rakiet krótkiego zasięgu, wyrzutnia 10, okręt 20) i baza lądowa z samymi żołnierzami."""
import uuid
from extensions import db
from models import Wojsko
from game.military_models import MilitaryBase, MilitaryFlight
from game.finance_service import FinanceError
from test_game_military_flights import FlightFixture


class SalvoTests(FlightFixture):
    def stock(self, **values):
        army = db.session.query(Wojsko).filter_by(panstwo_id=1).one()
        for field, value in values.items():
            setattr(army, field, value)
        db.session.commit()

    def test_fighter_carries_at_most_ten_short_range_missiles(self):
        base = self.source('air')
        with self.assertRaises(FinanceError) as error:
            self.launch(base, missiles=11)
        self.assertIn('najwyżej 10', str(error.exception))
        flight_id = self.launch(base, missiles=10, missile_type='medium')   # rodzaj z formularza ignorowany — zawsze krótkiego zasięgu
        db.session.expire_all()
        self.assertEqual(db.session.get(MilitaryFlight, flight_id).missile_type, 'short')
        self.assertEqual(db.session.query(Wojsko).filter_by(panstwo_id=1).one().rakiety_krotkiego_zasiegu, 10)

    def test_fighter_needs_short_range_stock(self):
        self.stock(rakiety_krotkiego_zasiegu=0, rakiety_sredniego_zasiegu=50)
        with self.assertRaises(FinanceError):
            self.launch(self.source('air'), missiles=1, missile_type='medium')

    def test_land_base_fires_ten_per_launcher(self):
        base = self.source('land')
        with self.assertRaises(FinanceError) as error:
            self.launch(base, missiles=11)
        self.assertIn('1 wyrzutni', str(error.exception))
        base.garrison = {'launchers': 2}; db.session.commit()
        self.assertTrue(self.launch(base, missiles=20))

    def test_warship_fires_at_most_twenty(self):
        self.stock(rakiety_krotkiego_zasiegu=50)
        from models import Region
        db.session.get(Region, 2).region_polozenie_id = 2   # nadmorski region celu
        base = MilitaryBase(panstwo_id=1, region_id=1, kind='naval', level=1, garrison={'warships': 1}, map_x=0, map_y=0)
        db.session.add(base); db.session.commit()
        with self.assertRaises(FinanceError) as error:
            self.launch(base, missiles=21)
        self.assertIn('20 rakiet', str(error.exception))
        self.assertTrue(self.launch(base, missiles=20))


class SoldiersOnlyBaseTests(FlightFixture):
    def deploy(self, kind, garrison):
        self.change('deploy', kind=kind, region_id=1, garrison=garrison, request_id=str(uuid.uuid4()))

    def test_land_base_may_have_only_soldiers(self):
        self.deploy('land', {'soldiers': 100, 'tanks': 0, 'launchers': 0, 'armored': 0})
        base = db.session.query(MilitaryBase).filter_by(kind='land').order_by(MilitaryBase.id.desc()).first()
        self.assertEqual(base.garrison['soldiers'], 100)

    def test_other_bases_still_need_equipment(self):
        with self.assertRaises(FinanceError) as error:
            self.deploy('air', {'soldiers': 100, 'fighters': 0})
        self.assertIn('sprzętu', str(error.exception))
