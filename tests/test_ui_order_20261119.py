"""19 Nov 2026: kolejność towarów (handel, magazyn na pasku bocznym) i obrona przeciwrakietowa na mapie panelu państwa."""
import unittest
from pathlib import Path

from services.natural_resources import RESOURCES
from game.industry_catalog import GOODS,ARMY_GOODS

ROOT=Path(__file__).resolve().parents[1]
MINED=[code for code,_ in RESOURCES]
FACTORY=[code for code in GOODS if code not in ARMY_GOODS]


class UiOrderTest(unittest.TestCase):

    def test_trade_goods_order_mined_then_factory_then_military(self):
        from game.commerce import goods_order
        from game.trade_goods import AMMUNITION
        order=goods_order()
        assert order[:len(MINED)]==MINED
        assert order[len(MINED):len(MINED)+len(FACTORY)]==FACTORY
        military=order[len(MINED)+len(FACTORY):]
        assert set(military)=={code for code in GOODS if code in ARMY_GOODS}|{AMMUNITION}
        assert len(order)==len(set(order))


    def test_trade_js_uses_explicit_order(self):
        source=(ROOT/'static/js/game_trade.js').read_text()
        assert 'config.resourceOrder' in source


    def test_sidebar_warehouse_mined_then_factory_without_military(self):
        from game.sidebar import WAREHOUSE_KEYS
        from game.trade_goods import AMMUNITION
        assert WAREHOUSE_KEYS==MINED+FACTORY
        assert not set(WAREHOUSE_KEYS)&(set(ARMY_GOODS)|{AMMUNITION})


    def test_panel_defense_layers(self):
        source=(ROOT/'game/main_panel.py').read_text()
        # obrona regionu w filtrze obrony, obrona obiektu w warstwie obiektu
        assert "'region':'defenses'" in source and "'mine':'mines'" in source and "'radar':'radars'" in source
        js=(ROOT/'static/js/game_panel_map.js').read_text()
        assert "item.defense === 'region'" in js and 'regionCenter' in js


if __name__=='__main__':
    unittest.main()
