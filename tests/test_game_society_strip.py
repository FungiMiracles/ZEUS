"""Pasek wskaźników społecznych (22 Nov 2026): progi kolorów, trend dwóch ostatnich zmian, zapis zmian ORM."""
import unittest
from pathlib import Path

from flask import Flask, render_template_string

from extensions import db
from game import society_strip as strip
from game.society_strip import GameSocietyTrend, install, society_strip, tone, trend
from models import Panstwo, Spoleczenstwo


class ToneAndTrendTest(unittest.TestCase):
    def test_thresholds_for_positive_indicators(self):
        self.assertEqual([tone(v, True) for v in (71, 70, 69, 60, 59, 40, 39, 0)],
                         ['good', 'good', 'warn', 'warn', 'warn', 'warn', 'bad', 'bad'])

    def test_thresholds_for_harmful_indicators(self):
        self.assertEqual([tone(v, False) for v in (71, 70, 60, 59, 30, 29, 0)],
                         ['bad', 'neutral', 'neutral', 'warn', 'warn', 'good', 'good'])
        self.assertEqual(tone(None, False), 'neutral')

    def test_trend_from_last_two_changes(self):
        self.assertEqual(trend(1, 1), 'up')
        self.assertEqual(trend(-1, -1), 'down')
        self.assertEqual(trend(1, -1), 'mixed')
        self.assertEqual(trend(-1, 1), 'mixed')
        self.assertEqual(trend(1, None), 'up')
        self.assertIsNone(trend(None, None))


class RecordingTest(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.app = Flask(__name__, template_folder=str(root / 'templates'))
        self.app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        db.init_app(self.app)
        self.ctx = self.app.app_context(); self.ctx.push()
        db.metadata.create_all(db.engine, tables=[Panstwo.__table__, Spoleczenstwo.__table__, GameSocietyTrend.__table__])
        strip._ready.clear()
        install()
        db.session.add(Panstwo(PANSTWO_ID=7, panstwo_nazwa='Ozilandia'))
        db.session.add(Spoleczenstwo(panstwo_id=7, stabilnosc_spoleczna=50, zadowolenie_spoleczne=80, poziom_edukacji=65,
                                     zdrowie_publiczne=30, przestepczosc=20, radykalizacja_spoleczna=45,
                                     nierownosci_spoleczne=75, zaufanie_do_wladzy=55))
        db.session.commit()

    def tearDown(self):
        db.session.remove(); self.ctx.pop()

    def change(self, **values):
        society = db.session.query(Spoleczenstwo).filter_by(panstwo_id=7).one()
        for field, value in values.items():
            setattr(society, field, value)
        db.session.commit()

    def items(self):
        return {item['field']: item for item in society_strip(db.session, 7)}

    def test_changes_from_any_module_update_trend(self):
        self.assertIsNone(self.items()['przestepczosc']['trend'])
        self.change(przestepczosc=22, zaufanie_do_wladzy=50)
        self.change(przestepczosc=25, zaufanie_do_wladzy=52)
        self.change(stabilnosc_spoleczna=50)          # bez zmiany wartości — nie liczy się
        items = self.items()
        self.assertEqual(items['przestepczosc']['trend'], 'up')
        self.assertEqual(items['zaufanie_do_wladzy']['trend'], 'mixed')
        self.assertIsNone(items['stabilnosc_spoleczna']['trend'])
        self.change(przestepczosc=21); self.change(przestepczosc=19)
        self.assertEqual(self.items()['przestepczosc']['trend'], 'down')
        self.assertEqual(db.session.query(GameSocietyTrend).count(), 2)

    def test_strip_order_tones_and_template(self):
        items = society_strip(db.session, 7)
        self.assertEqual([i['label'] for i in items], ['Stabilność społeczna', 'Zadowolenie społeczne', 'Edukacja', 'Zdrowie',
                                                     'Przestępczość', 'Radykalizacja', 'Nierówności społeczne', 'Zaufanie do władzy'])
        self.assertEqual([i['tone'] for i in items], ['warn', 'good', 'warn', 'bad', 'good', 'warn', 'bad', 'warn'])
        self.change(poziom_edukacji=66); self.change(poziom_edukacji=64)
        source = (Path(__file__).resolve().parents[1] / 'templates/game/game_base_layout.html').read_text()
        block = source[source.index('{% if game_society_strip %}'):source.index('{# 13 Nov 2026: pasek wiadomości')]
        html = render_template_string(block, game_society_strip=society_strip(db.session, 7))
        self.assertIn('society-chip tone-bad', html)
        self.assertIn('trend-mixed', html)
        self.assertEqual(html.count('<li class="society-chip'), 8)

    def test_missing_table_is_ignored(self):
        GameSocietyTrend.__table__.drop(db.engine); strip._ready.clear()
        self.change(przestepczosc=40)
        self.assertIsNone(self.items()['przestepczosc']['trend'])


if __name__ == '__main__':
    unittest.main()
