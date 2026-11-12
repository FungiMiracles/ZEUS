from datetime import datetime
from contextlib import ExitStack, redirect_stdout
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch
from sqlalchemy import select

from game_features_support import FeatureTestCase
from extensions import db
from game.event_models import GeneratedEventSnapshot
from game.event_notifications import queue_generated_event
from game.forum_models import GameNotification
from game.models import GameUser
from models import Zdarzenie, RegionStateHistory, SpoleczenstwoStateHistory


class EventNotificationTests(FeatureTestCase):
    def make_event(self, country=1):
        event = Zdarzenie(zdarzenie_typ='powodz', panstwo_id=country,
                          region_id=country if country in [1, 2] else None,
                          opis_wygenerowany='Rzeka wystąpiła z brzegów.',
                          data_entenda=datetime(3010, 1, 2), data_rzeczywista=datetime(2026, 10, 23))
        db.session.add(event)
        db.session.flush()
        return event

    def test_effects_notification_owner_deduplication_and_retention(self):
        event = self.make_event()
        event_id = event.zdarzenie_id
        db.session.add(RegionStateHistory(id=1, region_id=1, event_id=event_id, source='EVENT',
            data_entenda=event.data_entenda, data_rzeczywista=datetime(2026, 10, 23),
            old_drogi=70, new_drogi=60, old_ludnosc=1000, new_ludnosc=990,
            old_zanieczyszczenie_powietrza=10, new_zanieczyszczenie_powietrza=12))
        db.session.add(SpoleczenstwoStateHistory(id=1, panstwo_id=1, event_id=event_id, source='EVENT',
            data_entenda=event.data_entenda.date(), old_stabilnosc=50, new_stabilnosc=49.5))
        queue_generated_event(event)
        queue_generated_event(event)
        db.session.commit()
        self.assertEqual(self.count(GameNotification), 1)
        snapshot = db.session.scalar(select(GeneratedEventSnapshot))
        values = {effect['label']: effect['value'] for effect in snapshot.effects}
        self.assertEqual(values['Drogi'], -10)
        self.assertEqual(values['Ludność'], -10)
        self.assertEqual(values['Stabilność'], -.5)
        feed = self.client.get('/game/forum/powiadomienia').json
        self.assertEqual(feed['items'][0]['kind'], 'GENERATED_EVENT')
        self.assertIn('Generator Zdarzeń', feed['items'][0]['text'])
        self.assertEqual(feed['items'][0]['effects'], snapshot.effects)
        url = feed['items'][0]['open_url']
        self.login(2)
        self.assertEqual(self.post(url).status_code, 404)
        self.login(1)
        event.opis_wygenerowany = 'Zmieniony opis'
        db.session.delete(event)
        db.session.commit()
        detail = self.post(url)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json['event']['content'], 'Rzeka wystąpiła z brzegów.')
        self.assertEqual(detail.json['event']['effects'], snapshot.effects)
        self.assertEqual(self.client.get('/game/forum/powiadomienia').json['unread_count'], 0)

    def test_no_user_inactive_user_and_transaction_rollback(self):
        event = self.make_event(4)
        queue_generated_event(event)
        self.assertEqual(self.count(GeneratedEventSnapshot), 0)
        db.session.get(GameUser, 2).is_active = False
        event = self.make_event(2)
        queue_generated_event(event)
        self.assertEqual(self.count(GameNotification), 0)
        event = self.make_event()
        queue_generated_event(event)
        self.assertEqual(self.count(GeneratedEventSnapshot), 1)
        db.session.rollback()
        self.assertEqual(self.count(GeneratedEventSnapshot), 0)
        self.assertEqual(self.count(GameNotification), 0)
        self.assertEqual(self.count(Zdarzenie), 0)

    def test_no_effects_and_missing_description(self):
        event = self.make_event()
        event.opis_wygenerowany = None
        queue_generated_event(event)
        db.session.commit()
        snapshot = db.session.scalar(select(GeneratedEventSnapshot))
        self.assertIn('Brak opisu', snapshot.content)
        self.assertEqual(snapshot.effects, [])

    def test_generator_queues_notifications_in_both_creation_paths(self):
        from engine import generator
        for fallback in [False, True]:
            with self.subTest(fallback=fallback), ExitStack() as stack:
                event = self.make_event()
                event.zdarzenie_typ = 'pozar_lasu' if fallback else 'trzesienie_ziemi'
                for name in dir(generator):
                    if name.startswith('try_generate_'):
                        stack.enter_context(patch.object(generator, name, return_value=None))
                if fallback:
                    stack.enter_context(patch.object(generator, 'try_generate_wildfire', side_effect=[None, event]))
                else:
                    stack.enter_context(patch.object(generator, 'try_generate_earthquake', return_value=event))
                    def apply_effect(**kwargs):
                        db.session.add(RegionStateHistory(
                            id=10, region_id=1, event_id=event.zdarzenie_id, source='EVENT',
                            data_entenda=event.data_entenda, data_rzeczywista=datetime(2026, 10, 23),
                            old_drogi=80, new_drogi=75))
                    stack.enter_context(patch.object(generator, 'apply_earthquake_effect', side_effect=apply_effect))
                stack.enter_context(patch.object(generator, 'MAX_EVENTS_PER_MONTH', 1))
                stack.enter_context(patch.object(generator, 'select_regions', return_value=[SimpleNamespace(region_id=1)]))
                for name in ['get_month_event_count', 'get_region_month_event_count', 'get_week_event_count', 'get_day_event_count']:
                    stack.enter_context(patch.object(generator, name, return_value=0))
                stack.enter_context(patch.object(generator, 'select_template', return_value=None))
                stack.enter_context(patch.object(generator.random, 'shuffle'))
                with redirect_stdout(StringIO()):
                    self.assertEqual(generator.generate_events_for_month(datetime(3010, 1, 1)), 1)
                snapshot = db.session.scalar(select(GeneratedEventSnapshot).where(GeneratedEventSnapshot.source_event_id == event.zdarzenie_id))
                self.assertIsNotNone(snapshot)
                if not fallback:
                    self.assertEqual(snapshot.effects[0]['value'], -5)
        self.assertEqual(self.count(GameNotification), 2)
