"""Naval routing respects the two kilometre coastal exclusion zone."""
import unittest
from unittest.mock import patch
from shapely.geometry import box,LineString,Point
from game.sea_routes import SeaRouter,naval_sea_route,_navy_router,path_position
from game.finance_service import FinanceError

class NavalClearanceTests(unittest.TestCase):
    def setUp(self):
        # Other naval modules populate these caches with real map geometry.
        # This suite substitutes its own geometry and must start with empty caches.
        naval_sea_route.cache_clear();_navy_router.cache_clear()

    def tearDown(self):
        naval_sea_route.cache_clear();_navy_router.cache_clear()

    def test_detour_stays_two_km_offshore(self):
        land=box(0,0,10,10)
        with patch('game.sea_routes._world_router',return_value=SeaRouter(land,resolution=100)):
            route=naval_sea_route((-5,5),(15,5),1)
            self.assertGreater(len(route),2)
            self.assertGreaterEqual(LineString(route).distance(land),2)
            self.assertGreaterEqual(Point(path_position(route,.5)).distance(land),2)

    def test_target_on_land_or_in_coastal_zone_rejected(self):
        with patch('game.sea_routes._world_router',return_value=SeaRouter(box(0,0,10,10),resolution=100)):
            for target in [(5,5),(11,5),(12,5)]:
                with self.subTest(target=target),self.assertRaises(FinanceError):
                    naval_sea_route((-5,5),target,1)

    def test_base_departure_projects_to_safe_water(self):
        land=box(0,0,10,10)
        with patch('game.sea_routes._world_router',return_value=SeaRouter(land,resolution=100)):
            route=naval_sea_route((.5,5),(-10,5),1)
            self.assertGreaterEqual(LineString(route).distance(land),2)
