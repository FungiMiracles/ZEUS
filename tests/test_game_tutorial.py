"""Samouczek po pierwszym wejściu do gry (15 Nov 2026): odmiana nazw państw, jednorazowe wyświetlenie, CSRF."""
import unittest
from flask import render_template_string
from sqlalchemy import update
from game_features_support import FeatureTestCase
from extensions import db
from models import Panstwo
from game.country_names import genitive
from game.tutorial import tutorial_bp,GameUserTutorial


class GenitiveTests(unittest.TestCase):
    def test_regular_endings_and_exceptions(self):
        cases={'Ozilandia':'Ozilandii','Tunganiria':'Tunganirii','Maurycja':'Maurycji','Hasja':'Hasji','Irea':'Irei','Alata':'Alaty',
               'Sajstan':'Sajstanu','Mostol':'Mostolu','Ikko':'Ikko','Cicirici':'Cicirici','Czymony':'Czymonów',
               'Wyspy Wężowe':'Wysp Wężowych','Republika Zontyjska':'Republiki Zontyjskiej','Kosliw Północny':'Kosliwu Północnego',
               'Iskalia i Wyspy':'Iskalii i Wysp'}
        for name,expected in cases.items():self.assertEqual(genitive(name),expected,name)
        self.assertEqual(genitive('Nowe Państwo'),'państwa Nowe Państwo')   # nieznana nazwa wielowyrazowa — bez zgadywania
        self.assertEqual(genitive(None),'państwa')


class TutorialTests(FeatureTestCase):
    def setUp(self):
        super().setUp()
        self.app.register_blueprint(tutorial_bp)
        GameUserTutorial.__table__.create(db.engine,checkfirst=True)
        db.session.execute(update(Panstwo).where(Panstwo.PANSTWO_ID==1).values(panstwo_nazwa='Ozilandia'));db.session.commit()
        view=lambda:render_template_string('{% for t in game_tutorials or [] %}[{{ t.key }}|{{ t.title }}|{{ t.mobile }}|{{ t.desktop }}]{% endfor %}')
        self.app.add_url_rule('/game/test-samouczka','test_page',view)
        self.app.add_url_rule('/game/badania-test','game_research.page',view)   # ten sam endpoint co ekran badań
        with self.client.session_transaction() as session:session.update(game_user_id=1,game_csrf_token='token')

    def close(self,key,csrf='token'):
        return self.client.post('/game/samouczek/przeczytany',data={'csrf_token':csrf,'tutorial':key})

    def test_welcome_texts_for_mobile_and_desktop(self):
        page=self.client.get('/game/test-samouczka').text
        self.assertIn('[main|Witaj w grze|Zostałeś przywódcą Ozilandii. Zarządzaj wszystkimi sektorami państwa z poziomu menu w prawym górnym rogu ekranu głównego. W sekcji „Badania i rozwój” kupuj punkty',page)
        self.assertIn('|Zostałeś przywódcą Ozilandii. Zarządzaj wszystkimi sektorami państwa z poziomu menu u góry ekranu. W sekcji',page)
        self.assertIn('środowiskowe i informatyczne.',page)

    def test_welcome_then_section_each_shown_once(self):
        page=self.client.get('/game/badania-test').text
        self.assertLess(page.index('[main|'),page.index('[research|Badania i rozwój|Za 150 mln ROI możesz kupić 1 punkt rozwoju.'))
        self.assertEqual(self.close('main').status_code,200)
        page=self.client.get('/game/badania-test').text
        self.assertNotIn('[main|',page);self.assertIn('[research|',page)
        self.assertEqual(self.close('research').status_code,200);self.assertEqual(self.close('research').status_code,200)   # powtórnie — bez błędu
        self.assertEqual(self.client.get('/game/badania-test').text,'')
        self.assertEqual(self.client.get('/game/test-samouczka').text,'')                   # ekran bez komunikatu sekcji
        self.assertEqual(db.session.query(GameUserTutorial).count(),2)

    def test_every_section_has_its_screen_and_text(self):
        from game.tutorial import SECTIONS
        self.assertEqual(set(SECTIONS),{'research','forum','finance','war','intelligence','diplomacy','defense','trade'})
        self.assertIn('Państwa, które nie posiadają graczy również publikują swoje.',SECTIONS['forum'][2])
        self.assertIn('stawki celne za korzystanie ze swoich portów',SECTIONS['trade'][2])

    def test_requires_csrf_login_country_and_known_key(self):
        self.assertEqual(self.close('main',csrf='zly').status_code,400)
        self.assertEqual(self.close('nieznany').status_code,400)
        self.assertEqual(db.session.query(GameUserTutorial).count(),0)
        with self.client.session_transaction() as session:session.pop('game_user_id')
        self.assertEqual(self.close('main').status_code,401)
        self.assertEqual(self.client.get('/game/test-samouczka').text,'')

    def test_missing_table_does_not_break_pages(self):
        GameUserTutorial.__table__.drop(db.engine)
        self.assertEqual(self.client.get('/game/test-samouczka').text,'')


class GuardTests(unittest.TestCase):
    def test_tutorial_routes_pass_the_wiki_login_guard(self):
        # 15 Nov 2026: bez wpisu na liście blueprintów gry zapis odczytu był przekierowywany na /wejscie,
        # więc powitanie wracało na każdym ekranie. Testowe aplikacje nie mają tej ochrony — sprawdzamy listę w zeus_app.
        import ast,pathlib
        tree=ast.parse(pathlib.Path(__file__).resolve().parents[1].joinpath('zeus_app.py').read_text(encoding='utf-8'))
        guard=next(node for node in ast.walk(tree) if isinstance(node,ast.FunctionDef) and node.name=='wymus_wejscie')
        allowed=set()
        for node in ast.walk(guard):
            if isinstance(node,ast.Compare) and isinstance(node.left,ast.Attribute) and node.left.attr=='blueprint' and isinstance(node.comparators[0],ast.Set):
                allowed|={item.value for item in node.comparators[0].elts}
        self.assertIn(tutorial_bp.name,allowed)
