"""Wody terytorialne (15 Nov 2026): podział pasa 100 km linią środkową, wejścia obcych okrętów i powiadomienia."""
import unittest
from datetime import timedelta
from unittest.mock import patch
import shapely
from shapely.geometry import box, mapping
from extensions import db
from test_game_military import MilitaryFixture, NOW
from game.forum_models import GameNotification
from game import territorial_waters
from game.territorial_waters import compute_region_waters, entries


def feature(region_id, geometry):
    return {'type': 'Feature', 'properties': {'region_id': region_id}, 'geometry': mapping(geometry)}


class GeometryTests(unittest.TestCase):
    def test_waters_are_a_100_km_band_split_by_the_median_line(self):
        # Dwa sąsiednie regiony na wybrzeżu i wyspa trzeciego regionu 30 jednostek dalej (pas 25 jednostek).
        features = [feature(1, box(0, 0, 10, 10)), feature(2, box(10, 0, 20, 10)), feature(3, box(50, 0, 60, 10)),
                    feature(None, box(0, 100, 5, 105))]
        waters = compute_region_waters(features, 25)
        land = shapely.union_all([box(0, 0, 20, 10), box(50, 0, 60, 10), box(0, 100, 5, 105)])
        band = shapely.difference(shapely.buffer(land, 25), land)
        self.assertEqual(set(waters), {1, 2, 3}, 'ląd bez regionu nie ma wód')
        total = shapely.union_all(list(waters.values()))
        for a in waters:
            for b in waters:
                if a < b:
                    self.assertLess(shapely.intersection(waters[a], waters[b]).area, 1e-6, 'wody regionów się nie nakładają')
        self.assertLess(shapely.difference(total, band).area, 1e-6, 'wody nie wychodzą poza pas od lądu')
        # Punkt 1 jednostkę od brzegu regionu 1 należy do regionu 1; punkt pośrodku cieśniny 20–50 dzieli linia środkowa (x=35).
        self.assertTrue(waters[1].covers(shapely.Point(5, -1)))
        self.assertTrue(waters[2].covers(shapely.Point(34, 5)) and waters[3].covers(shapely.Point(36, 5)))
        self.assertFalse(total.covers(shapely.Point(5, -30)), '30 jednostek od brzegu to morze otwarte')
        self.assertFalse(any(zone.covers(shapely.Point(2, 102)) for zone in waters.values()))

    def test_entries_along_the_route(self):
        zones = {7: box(10, -5, 20, 5), 8: box(0, -5, 4, 5)}
        found = entries([[0, 0], [30, 0]], zones, skip_country=None)
        self.assertEqual([(country, number, round(fraction, 6)) for country, number, fraction, _ in found], [(7, 1, round(10 / 30, 6))],
                         'trasa zaczynająca się w strefie 8 nie jest wejściem')
        back = entries([[0, 0], [30, 0], [0, 0.5]], zones)
        self.assertEqual([(country, number) for country, number, _, _ in back], [(7, 1), (7, 2), (8, 1)])
        self.assertEqual(entries([[0, 0], [30, 0]], zones, skip_country=7), [], 'własne wody nie są wejściem')


class IncursionTests(MilitaryFixture):
    def setUp(self):
        super().setUp()
        from game.military_models import MilitaryVessel
        from game.territorial_waters_models import TerritorialIncursion
        for model in (MilitaryVessel, TerritorialIncursion):
            model.__table__.create(db.engine, checkfirst=True)
        self.vessel = MilitaryVessel(panstwo_id=2, kind='warships', status='sailing', source_x=0, source_y=0, target_x=30, target_y=0,
                                     starts_at=NOW, arrives_at=NOW + timedelta(hours=30), health=100)
        db.session.add(self.vessel)
        db.session.commit()
        zones = {1: box(10, -5, 20, 5), 2: box(-5, -5, 3, 5)}
        for target, value in (('game.territorial_waters.country_waters', zones), ('game.military_navy.vessel_route', [[0, 0], [30, 0]])):
            stub = patch(target, return_value=value); stub.start(); self.addCleanup(stub.stop)

    def detect(self, now):
        from sqlalchemy.orm import Session
        with Session(db.engine) as session, session.begin():
            return territorial_waters.detect_incursions(session, now)

    def notes(self):
        return [n.system_text for n in db.session.query(GameNotification) if 'Wody terytorialne' in (n.system_text or '')]

    def test_one_notification_when_a_foreign_vessel_enters_and_none_before(self):
        self.assertEqual(self.detect(NOW + timedelta(hours=9)), 0, 'okręt jeszcze nie dopłynął do granicy wód')
        self.assertEqual(self.detect(NOW + timedelta(hours=25)), 1, 'wejście po 10 h zauważone, choć harmonogram ruszył później')
        self.assertEqual(self.detect(NOW + timedelta(hours=26)), 0, 'bez powtórzeń')
        notes = self.notes()
        self.assertEqual(len(notes), 1)
        self.assertIn('Okręt wojenny', notes[0])
        self.assertIn('2990-01-01 10:00', notes[0])
        from game.territorial_waters_models import TerritorialIncursion
        row = db.session.query(TerritorialIncursion).one()
        self.assertEqual((row.vessel_country_id, row.waters_country_id, row.entry_no, round(row.point_x, 6)), (2, 1, 1, 10))

    def test_coastal_route_entering_the_same_waters_twice_gives_one_notification(self):
        with patch('game.military_navy.vessel_route', return_value=[[0, 0], [30, 0], [0, 0.5]]):
            self.detect(NOW + timedelta(hours=30))
        self.assertEqual(len(self.notes()), 1)

    def test_new_voyage_through_the_same_waters_is_a_new_entry(self):
        self.detect(NOW + timedelta(hours=30))
        self.vessel = db.session.merge(self.vessel)
        self.vessel.starts_at = NOW + timedelta(hours=40); self.vessel.arrives_at = NOW + timedelta(hours=70)
        db.session.commit()
        self.detect(NOW + timedelta(hours=70))
        self.assertEqual(len(self.notes()), 2)


if __name__ == '__main__':
    unittest.main()
