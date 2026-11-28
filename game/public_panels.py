"""Społeczeństwo i informacje o zmianach dla gracza."""
from datetime import datetime,timedelta
from flask import Blueprint,render_template,redirect,url_for,request
from sqlalchemy import select,func
from sqlalchemy.orm import lazyload
from extensions import db
from models import Panstwo,Region,Spoleczenstwo,Zdarzenie,ZdarzenieSzablon,RegionStateHistory,SpoleczenstwoStateHistory,MiastoStateHistory
from game.forum import player
from game.country_summary import country_summary
from game.governance import controlled_ids
from game.event_models import GeneratedEventSnapshot
from game.event_notifications import REGION_EFFECTS,SOCIAL_EFFECTS
from services.society_indicators import INDICATORS

public_panels_bp=Blueprint('game_public',__name__,url_prefix='/game')


def context(user,country,active):
    return {'game_user':user,'game_country':country_summary(country),'game_home_url':url_for('game_main_page'),'game_logout_url':url_for('game_logout'),'game_active_page':active}


@public_panels_bp.get('/informacje-o-zmianach')
def changes():
    user,country=player()
    if user is None:return redirect(url_for('wejscie'))
    from pathlib import Path
    import markdown
    document=Path(__file__).resolve().parents[1]/'changelog'/'ENTENDA_GAME_CHANGELOG.md'
    content=markdown.markdown(document.read_text(encoding='utf-8'),extensions=['extra','sane_lists'])
    return render_template('game/changes.html',changelog_html=content,**context(user,country,'changes'))


@public_panels_bp.get('/spoleczenstwo')
def society():
    user,country=player()
    if user is None:return redirect(url_for('wejscie'))
    row=db.session.scalar(select(Spoleczenstwo).options(lazyload('*')).where(Spoleczenstwo.panstwo_id==country.PANSTWO_ID))
    indicators=[{**item,'value':getattr(row,item['field']) if row else None} for item in INDICATORS]
    from decimal import Decimal,ROUND_HALF_UP,localcontext
    from game.finance_service import game_now,period_key
    from game.finance_models import StateBudget
    from game.social_benefits import details,expectations
    year,half=period_key(game_now())
    budget=db.session.scalar(select(StateBudget).where(StateBudget.panstwo_id==country.PANSTWO_ID,StateBudget.game_year==year,StateBudget.period==half))
    snapshot=details(db.session,budget) if budget else None
    expected=snapshot['expected'] if snapshot else expectations(db.session,country.PANSTWO_ID)
    with localcontext() as decimal_context:
        decimal_context.prec=64
        benefit_expectations={kind:format((expected[kind]/Decimal('1000000000')).quantize(Decimal('0.1'),rounding=ROUND_HALF_UP),'f').replace('.',',')+' MLD' if expected else '—' for kind in ('seniors','children')}
    return render_template('game/society.html',indicators=indicators,benefit_expectations=benefit_expectations,benefit_year=year,benefit_half=half,**context(user,country,'society'))


# 28 Nov 2026: ekran „Wydarzenia” pokazuje gazetę „Entenda News” (game.newspaper); lista generatora zdarzeń usunięta z gry.
