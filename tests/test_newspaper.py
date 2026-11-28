"""28 Nov 2026: gazeta „Entenda News” na ekranie „Wydarzenia” — fakty miesiąca, wydanie raz na miesiąc, model AI i tekst ZEUS."""
from datetime import datetime,timedelta
from unittest.mock import patch
from sqlalchemy import select
from extensions import db
from models import AudytStosunki
from game import newspaper
from game.newspaper import NewspaperIssue,newspaper_bp
from game.land_war_models import SovereigntyLoss
from game_features_support import FeatureTestCase

NOW=datetime(3002,8,3,12,0)
START,END=datetime(3002,7,1),datetime(3002,8,1)


class NewspaperTests(FeatureTestCase):
    def setUp(self):
        super().setUp();self.app.register_blueprint(newspaper_bp)
        from game.rail_models import RailLine
        from game.airport_models import Airport
        from game.imf_models import ImfLoan
        from game.base_permits import BasePermit
        from game.paga_ai_models import PagaAiControl
        from models import RegionZasob,DictZasob
        for model in (RailLine,Airport,ImfLoan,BasePermit,NewspaperIssue,PagaAiControl,RegionZasob,DictZasob):model.__table__.create(db.engine,checkfirst=True)
        clock=patch('game.finance_service.game_now',return_value=NOW);clock.start();self.addCleanup(clock.stop)

    def audit(self,id,a,b,state,at):
        db.session.add(AudytStosunki(id=id,panstwo_id=a,panstwo_id2=b,relacja_id=6,stan_id=state,data_zmiany_entenda=at,data_zmiany_rzeczywista=at))

    def world(self):
        self.audit(1,1,2,1,datetime(3002,6,1));self.audit(2,1,2,8,datetime(3002,7,5))     # wypowiedzenie wojny
        self.audit(3,2,3,8,datetime(3002,6,1));self.audit(4,2,3,2,datetime(3002,7,9))     # zawieszenie broni
        self.audit(5,1,3,8,datetime(3002,5,1));self.audit(6,1,3,1,datetime(3002,7,20))    # koniec wojny
        self.audit(7,1,4,8,datetime(3002,8,2))                                            # następny miesiąc — pominięty
        db.session.commit()

    def test_war_events_and_sovereignty_choose_the_lead(self):
        self.world()
        facts=newspaper.collect_facts(db.session,START,END,None,newspaper.snapshot(db.session,NOW))
        self.assertEqual(facts['lead']['kind'],'WAR_STARTED')
        self.assertEqual([item['kind'] for item in facts['news']],['WAR_ENDED','CEASEFIRE'])
        self.assertIn('Państwo 1',facts['lead']['fact']);self.assertFalse(facts['baseline'])
        db.session.add(SovereigntyLoss(panstwo_id=4,annexed_by=1,capital_region_id=1,lost_at=datetime(3002,7,15)));db.session.commit()
        facts=newspaper.collect_facts(db.session,START,END,None,{})
        self.assertEqual(facts['lead']['kind'],'SOVEREIGNTY_LOST');self.assertIn('Państwo Państwo 4 utraciło niepodległość',facts['lead']['fact'])
        self.assertEqual([item['id'] for item in [facts['lead'],*facts['news']]],[1,2,3,4])

    def test_snapshot_differences_technology_nuclear_and_permits(self):
        name=lambda id:f'Państwo {id}'
        previous={'technologies':{'1':['method']},'nuclear':{'2':0},'permits':[[1,1,2,1]]}
        current={'technologies':{'1':['method','mine_coal']},'nuclear':{'2':3,'3':0},'permits':[[1,1,2,1],[2,2,3,2]]}
        technology=newspaper._technologies(db.session,START,END,previous,current,name)
        self.assertEqual(len(technology),1);self.assertEqual(technology[0]['countries'],['Państwo 1'])
        nuclear=newspaper._nuclear(previous,current,name)
        self.assertEqual([item['countries'] for item in nuclear],[['Państwo 2']])
        permits=newspaper._permits(db.session,previous,current,name)
        self.assertEqual(len(permits),1);self.assertIn('Państwo Państwo 2 zezwoliło państwu Państwo 3',permits[0]['fact'])

    def test_technology_by_research_timer_without_baseline(self):
        from game.research_models import ResearchAccount
        from game.industry_catalog import TECHNOLOGIES
        node=next(code for code in TECHNOLOGIES if code!='method');cost=TECHNOLOGIES[node]['cost']
        db.session.add(ResearchAccount(panstwo_id=2,points=0,ammunition=0,nodes={node:cost},timers={node:{'started':'3002-06-20T00:00:00','ready':'3002-07-10T00:00:00'}}));db.session.commit()
        items=newspaper._technologies(db.session,START,END,None,{},lambda id:f'Państwo {id}')
        self.assertEqual(len(items),1);self.assertIn(TECHNOLOGIES[node]['label'],items[0]['fact'])
        self.assertEqual(newspaper._technologies(db.session,datetime(3002,8,1),datetime(3002,9,1),None,{},str),[])

    def test_imf_and_trade_statistics(self):
        from game.imf_models import ImfLoan
        db.session.add_all([ImfLoan(borrower_id=2,amount=5000000000,outstanding=5000000000,status='active',pool_year=3002,start_year=3002,start_period=3,due_year=3003,due_period=3,capacity=0,request_id='a',created_game_at=datetime(3002,7,3)),
                            ImfLoan(borrower_id=3,amount=9000000000,outstanding=0,status='rejected',pool_year=3002,start_year=3002,start_period=3,due_year=3003,due_period=3,capacity=0,request_id='b',created_game_at=datetime(3002,7,3))])
        db.session.commit()
        stats=newspaper.statistics(db.session,START,END,None,{},lambda id:f'Państwo {id}')
        self.assertEqual(stats['imf'],{'loans':1,'total_bln':5.0,'borrowers':['Państwo 2']})
        self.assertEqual(stats['trade']['shipments'],0)
        self.assertIn('MFW udzielił 1 pożyczek na łącznie 5,0 mld ROI (Państwo 2)',newspaper.stats_text(stats))

    def test_one_issue_per_month_published_by_zeus_when_ai_is_off(self):
        self.world()
        issue=newspaper.ensure_issue(db.session,NOW);db.session.commit()
        self.assertEqual((issue.game_year,issue.game_month),(3002,7))
        self.assertIsNone(newspaper.ensure_issue(db.session,NOW+timedelta(days=5)))
        self.assertEqual(newspaper.process(issue.id,writer=lambda facts:self.fail('AI wyłączone')),'PUBLISHED')
        db.session.expire_all();issue=db.session.get(NewspaperIssue,issue.id)
        self.assertEqual(issue.author,'ZEUS');self.assertTrue(issue.content['lead']['title'].startswith('Wybuch wojny'))
        self.assertIsNotNone(newspaper.ensure_issue(db.session,datetime(3002,9,2)))   # kolejny miesiąc — nowe wydanie

    def test_ai_text_is_merged_with_facts_and_failures_fall_back(self):
        from game.paga_ai_models import PagaAiControl
        db.session.add(PagaAiControl(id=1,enabled=True,revision=1));self.world()
        issue=newspaper.ensure_issue(db.session,NOW);db.session.commit()
        answer={'lead':{'title':'Wojna!','body':'Tekst '*500},'news':[{'id':2,'title':'Pokój','body':'Koniec wojny.'},{'id':99,'title':'Zmyślony','body':'x'}],'stats':{'title':'Liczby','body':'Spokojnie.'}}
        self.assertEqual(newspaper.process(issue.id,writer=lambda facts:(newspaper.merge_ai(facts,answer),'groq','test-model')),'PUBLISHED')
        db.session.expire_all();content=db.session.get(NewspaperIssue,issue.id).content
        self.assertEqual(content['lead']['title'],'Wojna!');self.assertLessEqual(len(content['lead']['body']),newspaper.TEXT_LIMITS['body'])
        self.assertEqual([item['title'] for item in content['news']],['Pokój','Zawieszenie broni: Państwo 2 – Państwo 3'])   # brak id 3 → tekst ZEUS; id 99 pominięte
        second=NewspaperIssue(game_year=3002,game_month=6,period_start=datetime(3002,6,1),period_end=datetime(3002,7,1),status='PENDING',facts=newspaper.collect_facts(db.session,datetime(3002,6,1),datetime(3002,7,1),None,{}),snapshot={},attempts=0,created_at=NOW)
        db.session.add(second);db.session.commit()
        def broken(facts):raise RuntimeError('limit')
        for attempt in range(newspaper.MAX_ATTEMPTS):
            row=db.session.get(NewspaperIssue,second.id);row.next_attempt_at=None;db.session.commit()
            status=newspaper.process(second.id,writer=broken);db.session.expire_all()
        self.assertEqual(status,'PUBLISHED');self.assertEqual(db.session.get(NewspaperIssue,second.id).author,'ZEUS')

    def test_screen_shows_newspaper_archive_and_hides_pending(self):
        html=self.client.get('/game/wydarzenia').get_data(as_text=True)
        self.assertIn('Entenda News',html);self.assertIn('Pierwsze wydanie już wkrótce',html);self.assertNotIn('Filtry wydarzeń',html)
        self.world();issue=newspaper.ensure_issue(db.session,NOW);db.session.commit();newspaper.process(issue.id);db.session.expire_all()
        html=self.client.get('/game/wydarzenia').get_data(as_text=True)
        self.assertIn('Najważniejsze wydarzenie miesiąca',html);self.assertIn('Wybuch wojny',html);self.assertIn('Z kraju i ze świata',html)
        self.assertIn('Miesiąc w liczbach',html);self.assertIn('lipiec 3002',html)
        pending=NewspaperIssue(game_year=3002,game_month=1,period_start=datetime(3002,1,1),period_end=datetime(3002,2,1),status='PENDING',facts={},snapshot={},attempts=0,created_at=NOW)
        db.session.add(pending);db.session.commit()
        self.assertEqual(self.client.get(f'/game/wydarzenia?wydanie={pending.id}').status_code,404)
        self.assertEqual(self.client.post('/game/wydarzenia').status_code,405)


    def budget(self,country,year=3002,period=3):
        from game.finance_models import StateBudget
        at=datetime(year,7,1)
        self.budget_id=getattr(self,'budget_id',0)+1
        db.session.add(StateBudget(id=self.budget_id,financial_period_id=1,panstwo_id=country,game_year=year,period=period,opening_reserve=0,tax_total=0,budget_total=0,
                                   expenditure_total=0,closing_reserve=0,approval_mode='MANUAL',approved_at=at,approved_game_date=at))

    def test_budgets_report_playing_countries_without_budget(self):
        from game.paga2.models import Paga2Profile
        Paga2Profile.__table__.create(db.engine,checkfirst=True)
        self.budget(1);self.budget(2);self.budget(4,period=2);db.session.commit()   # gracze 1–3; 4 nie gra — pomijane
        result=newspaper.budgets(db.session,START,str)
        self.assertEqual(result['period'],'III kwartał 3002')
        self.assertEqual((result['expected'],result['set'],result['all'],result['missing']),(3,2,False,['3']))
        self.assertIn('nie ustaliły go jeszcze: 3',newspaper.budgets_text(result))
        self.budget(3);db.session.commit()
        result=newspaper.budgets(db.session,START,str)
        self.assertTrue(result['all']);self.assertIn('wszystkie państwa w grze (3)',newspaper.budgets_text(result))

    def test_generator_events_top_five_by_scale(self):
        from models import Zdarzenie
        for id,scale,victims,day in [(1,2,0,3),(2,5,10,9),(3,5,40,20),(4,1,0,2),(5,3,0,4),(6,4,0,5),(7,5,0,1),(8,2,0,8)]:
            db.session.add(Zdarzenie(zdarzenie_id=id,zdarzenie_typ='test',region_id=1,skala=scale,ilosc_ofiar=victims,
                                     opis_wygenerowany=f'Państwo 1 : Opis {id}.',data_entenda=datetime(3002,7,day)))
        db.session.add(Zdarzenie(zdarzenie_id=9,zdarzenie_typ='test',region_id=1,skala=5,opis_wygenerowany='Inny miesiąc',data_entenda=datetime(3002,8,2)))
        db.session.add(Zdarzenie(zdarzenie_id=10,zdarzenie_typ='test',region_id=1,skala=5,opis_wygenerowany='Usunięte',data_entenda=datetime(3002,7,2),data_usuniecia=datetime(3002,7,3)))
        db.session.commit()
        items=newspaper.generator_events(db.session,START,END,lambda id:f'Państwo {id}')
        self.assertEqual([item['event_id'] for item in items],[3,2,7,6,5])
        self.assertEqual(items[0]['fact'],'Opis 3.');self.assertEqual(items[0]['country'],'Państwo 1');self.assertEqual(items[0]['region'],'Pierwszy region')
        facts=newspaper.collect_facts(db.session,START,END,None,{})
        content=newspaper.fallback_content(facts)
        self.assertEqual(len(content['events']),5);self.assertEqual(content['events'][0]['title'],'Pierwszy region, Państwo 1')
        answer={'lead':None,'news':[],'events':[{'id':facts['events'][0]['id'],'title':'Katastrofa','body':'Opis AI.'}],'stats':{'title':'T','body':'B'}}
        merged=newspaper.merge_ai(facts,answer)
        self.assertEqual(merged['events'][0]['title'],'Katastrofa');self.assertEqual(merged['events'][1]['title'],content['events'][1]['title'])
        brief=newspaper.prompt(facts)[1]['content'];self.assertIn('kronika_zdarzeń',brief);self.assertIn('budgets',brief)

    def test_screen_shows_map_chronicle_and_budgets(self):
        from models import Zdarzenie
        db.session.add(Zdarzenie(zdarzenie_id=1,zdarzenie_typ='test',region_id=1,skala=5,ilosc_ofiar=1200,opis_wygenerowany='Wielka powódź.',data_entenda=datetime(3002,7,4)))
        self.budget(1);db.session.commit()
        issue=newspaper.ensure_issue(db.session,NOW);db.session.commit();newspaper.process(issue.id);db.session.expire_all()
        html=self.client.get('/game/wydarzenia').get_data(as_text=True)
        self.assertIn('entenda_news_mapa.svg',html);self.assertIn('Kronika zdarzeń',html);self.assertIn('Wielka powódź.',html)
        self.assertIn('Ofiary: 1 200',html);self.assertIn('Nie wszystkie państwa ustaliły budżet',html);self.assertIn('Brak budżetu: Państwo 2, Państwo 3',html)


if __name__=='__main__':
    import unittest;unittest.main()
