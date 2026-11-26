"""Droga przemarszu wojsk lądowych (26 Nov 2026, game.land_routes): armia omija akweny (zatoki) drogą lądową
i nie wchodzi na terytorium państw spoza wojny; pozycja, czas, powrót po anulowaniu — po zapisanej trasie."""
import threading
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from shapely.geometry import LineString, box, mapping
from game import land_routes, land_war
from game.land_war_models import LandArmy
from test_land_war import LandWarFixture, NOW


def covered(land, path):
    return all(land.buffer(1e-6).covers(LineString([a, b])) for a, b in zip(path, path[1:]))


# Zatoka: ląd w kształcie litery U — woda między x 10–20 dla y > 10.
BAY = box(0, 0, 30, 10).union(box(0, 10, 10, 30)).union(box(20, 10, 30, 30))


class RouteGeometryTests(unittest.TestCase):
    def route(self, land, a, b):
        with patch('game.land_routes.territory', return_value=land):
            return land_routes.route(None, a, b, {1}, km_per_unit=1)

    def test_straight_line_over_land_is_kept(self):
        self.assertEqual(self.route(BAY, (2, 2), (28, 2)), [[2.0, 2.0], [28.0, 2.0]])

    def test_army_walks_around_the_bay(self):
        # Odbicie własnego miasta za zatoką: w linii prostej woda, ale drogą lądową da się dojść.
        path = self.route(BAY, (5, 25), (25, 25))
        self.assertIsNotNone(path)
        self.assertEqual((path[0], path[-1]), ([5.0, 25.0], [25.0, 25.0]))
        self.assertTrue(covered(BAY, path))
        self.assertGreater(land_routes.length(path), 40)          # objazd wokół zatoki (~42), nie 20 w linii prostej
        self.assertLess(min(p[1] for p in path), 10.5)            # przez „dno” litery U

    def test_island_is_unreachable(self):
        island = box(0, 0, 10, 10).union(box(20, 0, 30, 10))
        self.assertIsNone(self.route(island, (5, 5), (25, 5)))

    def test_endpoint_in_coastal_band(self):
        # Baza morska / miasto portowe tuż przy brzegu (do 4 km od lądu).
        self.assertIsNotNone(self.route(box(0, 0, 30, 10), (2, 2), (28, 12)))


class TerritoryTests(unittest.TestCase):
    """Terytorium dostępne dla armii: regiony stron wojny i ziemie niczyje; państwo neutralne zamknięte."""
    def setUp(self):
        land_routes._LOCAL.__dict__.clear()
        regions = {1: box(0, 0, 10, 10), 2: box(10, 0, 20, 10), 3: box(20, 0, 30, 10), 4: box(0, 10, 30, 20)}
        self.holders = {1: 1, 2: 5, 3: 3, 4: 3}          # 5 — państwo spoza wojny; 3 — przeciwnik
        features = [{'properties': {'region_id': rid}, 'geometry': mapping(shape)} for rid, shape in regions.items()]
        fake_path = SimpleNamespace(stat=lambda: SimpleNamespace(st_mtime_ns=1))
        def region_at(x, y):
            return next((rid for rid, shape in regions.items() if shape.contains(__import__('shapely').Point(x, y))), None)
        for target, kwargs in (('game.land_routes.holders', dict(side_effect=lambda session: self.holders)),
                               ('game.military_geography.map_features', dict(return_value=features)),
                               ('game.military_geography.MAP_PATH', dict(new=fake_path)),
                               ('game.land_war.region_at', dict(side_effect=region_at))):
            p = patch(target, **kwargs); p.start(); self.addCleanup(p.stop)

    def route(self, sides):
        land_routes._LOCAL.__dict__.clear()
        return land_routes.route(None, (5, 5), (25, 5), sides, km_per_unit=1)

    def test_neutral_country_is_bypassed_through_war_territory(self):
        path = self.route({1, 3})
        self.assertIsNotNone(path)
        # obejście przez region 4 (przeciwnik), nie przez środek państwa 5 (dozwolone tylko domknięcie szczelin, 0,5 km)
        allowed = box(0, 0, 10, 10).union(box(20, 0, 30, 10)).union(box(0, 10, 30, 20)).buffer(.6)
        self.assertTrue(covered(allowed, path))
        self.assertGreater(land_routes.length(path), 20.5)

    def test_no_route_when_only_neutral_land_connects(self):
        self.holders[4] = 5
        self.assertIsNone(self.route({1, 3}))

    def test_country_in_the_war_is_passable(self):
        self.assertEqual(self.route({1, 3, 5}), [[5.0, 5.0], [25.0, 5.0]])

    def test_unowned_land_is_passable(self):
        self.holders[2] = None
        self.assertEqual(self.route({1, 3}), [[5.0, 5.0], [25.0, 5.0]])


class ParticipantsTests(unittest.TestCase):
    def test_sides_of_the_war(self):
        wars = {1: [3, 4], 6: [3], 8: []}
        with patch('game.military_service.enemies', side_effect=lambda s, c: wars.get(c, [])), \
             patch('game.trade_diplomacy.allied_country_ids', return_value=[6, 8]), \
             patch('game.governance.controller_id', side_effect=lambda s, c: c):
            # nasze wojny (3, 4), sojusznik 6 walczy z 3; sojusznik 8 nie walczy — jego terytorium zamknięte
            self.assertEqual(land_routes.participants(None, 1, 3, 2), {1, 2, 3, 4, 6})


class RouteMarchTests(LandWarFixture):
    """Armia maszeruje po zapisanej drodze lądowej (objazd), nie po odcinku prostym."""
    DETOUR = [[0.0, 0.0], [0.0, 40.0], [100.0, 40.0], [100.0, 0.0]]      # baza (0,0) → cel (100,0): 180 km zamiast 100

    def invade_detour(self, **units):
        with patch('game.land_war.march_route', return_value=self.DETOUR):
            return self.invade(**units)

    def test_route_length_sets_distance_time_and_position(self):
        id = self.invade_detour(soldiers=100)
        army = self.army(id)
        self.assertEqual(army.route, self.DETOUR)
        self.assertAlmostEqual(army.distance_km, 180)
        self.assertEqual(army.arrives_at - army.starts_at, timedelta(hours=180 / 50))
        middle = army.starts_at + (army.arrives_at - army.starts_at) / 2
        self.assertEqual(tuple(round(v, 6) for v in land_war.army_position(army, middle)), (50.0, 40.0))
        self.assertEqual(land_war.army_data(army)['route'], self.DETOUR)

    def test_cancel_returns_along_the_route(self):
        id = self.invade_detour(soldiers=100)
        army = self.army(id)
        self.now = army.starts_at + (army.arrives_at - army.starts_at) / 2
        land_war.cancel_march(1, {'army_id': id})
        army = self.army(id)
        self.assertEqual(army.status, 'RETURNING')
        self.assertEqual([[round(v, 6) for v in p] for p in army.route], [[50.0, 40.0], [0.0, 40.0], [0.0, 0.0]])
        self.assertAlmostEqual(army.distance_km, 90)

    def test_no_land_route_rejects_and_keeps_garrison(self):
        with patch('game.land_war.march_route', return_value=None), self.assertRaises(Exception) as error:
            self.invade(soldiers=100)
        self.assertIn('drogi lądowej', str(error.exception))
        self.assertEqual(self.army_count(), 0)

    def army_count(self):
        from extensions import db
        return db.session.query(LandArmy).count()

    def test_route_preview(self):
        with patch('game.land_war.march_route', return_value=self.DETOUR):
            preview = land_war.route_preview(1, {'source_base_id': self.home.id, 'target_kind': 'base', 'target_id': self.enemy.id})
        self.assertEqual(preview['route'], self.DETOUR)
        self.assertAlmostEqual(preview['distanceKm'], 180)


if __name__ == '__main__':
    unittest.main()
