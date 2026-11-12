"""Społeczeństwo i odczyt generatora zdarzeń dla gracza."""
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


def effects_for(events):
    ids=[event.zdarzenie_id for event in events]
    totals={id:{} for id in ids}
    for model,fields in ((RegionStateHistory,REGION_EFFECTS),(SpoleczenstwoStateHistory,SOCIAL_EFFECTS)):
        for row in db.session.scalars(select(model).where(model.event_id.in_(ids)).options(lazyload('*'))):
            result=totals[row.event_id]
            for label,field in fields:
                old,new=getattr(row,'old_'+field),getattr(row,'new_'+field)
                if old is not None and new is not None:result[label]=result.get(label,0)+new-old
    for event_id,delta in db.session.execute(select(MiastoStateHistory.event_id,func.sum(MiastoStateHistory.change_delta)).where(MiastoStateHistory.event_id.in_(ids)).group_by(MiastoStateHistory.event_id)):
        if delta and 'Ludność' not in totals[event_id]:totals[event_id]['Ludność']=delta
    result={id:[{'label':label,'value':value} for label,value in values.items() if value] for id,values in totals.items()}
    for snapshot in db.session.scalars(select(GeneratedEventSnapshot).where(GeneratedEventSnapshot.source_event_id.in_(ids))):
        if snapshot.effects:
            merged={effect['label']:effect for effect in result[snapshot.source_event_id]}
            merged.update({effect['label']:effect for effect in snapshot.effects})
            result[snapshot.source_event_id]=list(merged.values())
    return result


@public_panels_bp.get('/wydarzenia')
def events():
    user,country=player()
    if user is None:return redirect(url_for('wejscie'))
    query=select(Zdarzenie,Region.region_nazwa,Panstwo.panstwo_nazwa).outerjoin(Region,Zdarzenie.region_id==Region.region_id).outerjoin(Panstwo,Panstwo.PANSTWO_ID==func.coalesce(Zdarzenie.panstwo_id,Region.panstwo_id)).outerjoin(ZdarzenieSzablon,Zdarzenie.opis_szablon_id==ZdarzenieSzablon.szablon_id)
    error=None
    try:
        if request.args.get('my_country')=='1':query=query.where(Panstwo.PANSTWO_ID.in_(controlled_ids(db.session,country.PANSTWO_ID)))
        for name,column in [('country',Panstwo.panstwo_nazwa),('region',Region.region_nazwa)]:
            value=request.args.get(name,'').strip()[:255]
            if value:query=query.where(func.lower(column).contains(value.lower(),autoescape=True))
        for name,column in [('typ',Zdarzenie.zdarzenie_typ),('status',Zdarzenie.status),('wariant',func.coalesce(func.nullif(Zdarzenie.wariant,''),ZdarzenieSzablon.wariant))]:
            value=request.args.get(name,'').strip()[:64]
            if value:query=query.where(column==value)
        for name,column in [('zdarzenie_id',Zdarzenie.zdarzenie_id),('panstwo_id',Panstwo.PANSTWO_ID),('region_id',Zdarzenie.region_id),('miasto_id',Zdarzenie.miasto_id),('szablon_id',Zdarzenie.opis_szablon_id),('skala',Zdarzenie.skala)]:
            value=request.args.get(name,'').strip()
            if value:
                if not value.isascii() or not value.isdecimal() or len(value)>10 or not 1<=int(value)<=2147483647:raise ValueError('Identyfikatory i skala muszą być dodatnimi liczbami całkowitymi.')
                query=query.where(column==int(value))
        for name,lower in [('ofiary_od',True),('ofiary_do',False)]:
            value=request.args.get(name,'').strip()
            if value:
                if not value.isascii() or not value.isdecimal() or len(value)>18:raise ValueError('Liczba ofiar musi być nieujemną liczbą całkowitą.')
                query=query.where(Zdarzenie.ilosc_ofiar>=int(value) if lower else Zdarzenie.ilosc_ofiar<=int(value))
        for name,column,end in [('data_od',Zdarzenie.data_entenda,False),('data_do',Zdarzenie.data_entenda,True),('data_usuniecia',Zdarzenie.data_usuniecia,None)]:
            value=request.args.get(name,'').strip()
            if value:
                date=datetime.strptime(value,'%Y-%m-%d')
                if end is None:query=query.where(column>=date,column<date+timedelta(days=1))
                else:query=query.where(column<date+timedelta(days=1) if end else column>=date)
        if request.args.get('data_od') and request.args.get('data_do') and request.args['data_od']>request.args['data_do']:raise ValueError('Data od nie może być późniejsza niż data do.')
        if request.args.get('ofiary_od') and request.args.get('ofiary_do') and int(request.args['ofiary_od'])>int(request.args['ofiary_do']):raise ValueError('Minimum ofiar przekracza maksimum.')
    except (ValueError,OverflowError) as exc:error=str(exc) if 'does not match' not in str(exc) else 'Podaj poprawną datę.'
    page=max(1,request.args.get('page',1,type=int) or 1)
    count=db.session.scalar(select(func.count()).select_from(query.subquery())) if not error else 0
    rows=list(db.session.execute(query.order_by(Zdarzenie.zdarzenie_id.desc()).limit(30).offset((page-1)*30))) if not error else []
    effects=effects_for([row[0] for row in rows]) if rows else {}
    types=list(db.session.scalars(select(Zdarzenie.zdarzenie_typ).distinct().order_by(Zdarzenie.zdarzenie_typ)))
    filters=request.args.to_dict();filters.pop('page',None)
    return render_template('game/events.html',rows=rows,event_flags={event.zdarzenie_id:url_for('static',filename='flags/'+name.replace(' ','_')+'.jpg') for event,region,name in rows if name},effects=effects,types=types,count=count,page=page,error=error,
        countries=list(db.session.scalars(select(Panstwo.panstwo_nazwa).order_by(Panstwo.panstwo_nazwa))),regions=list(db.session.scalars(select(Region.region_nazwa).order_by(Region.region_nazwa))),
        next_url=url_for('game_public.events',**{**filters,'page':page+1}) if page*30<count else None,
        previous_url=url_for('game_public.events',**{**filters,'page':page-1}) if page>1 else None,**context(user,country,'events')),400 if error else 200
