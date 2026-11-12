"""Trade cargo uses the same ammunition stock as factories and missile defense."""
from sqlalchemy import select
from game.finance_service import FinanceError
from game.commerce_models import TradeOffer
from game.industry_catalog import GOODS,ARMY_GOODS

AMMUNITION='interceptor_ammunition'
AMMUNITION_LABEL='Amunicja przeciwrakietowa'


def change_goods(session,country_id,code,delta):
    if code==AMMUNITION:
        from game.research_service import account_for
        account=account_for(session,country_id)
        value=account.ammunition+delta
        if value<0:raise FinanceError('Brak dostatecznej ilości amunicji przeciwrakietowej w magazynie.')
        if value>9223372036854775807:raise FinanceError('Magazyn amunicji jest pełny.')
        account.ammunition=value
    elif code in ARMY_GOODS:
        from game.governance import army_for_country
        from game.military_service import active_counts
        from game.military_models import MilitaryBase
        from models import Wojsko
        row=army_for_country(session,country_id,lock=True)
        if row is None:
            row=Wojsko(panstwo_id=country_id);session.add(row)
        field=ARMY_GOODS[code];value=(getattr(row,field) or 0)+delta
        active=active_counts(list(session.scalars(select(MilitaryBase).where(MilitaryBase.panstwo_id==country_id))),session,country_id)
        if value<active.get(field,0):raise FinanceError('Nie można sprzedać uzbrojenia rozmieszczonego w bazach lub używanego w misji.')
        if value>2147483647:raise FinanceError('Przekroczony limit zasobów wojskowych.')
        setattr(row,field,value)
    else:
        from game.mining_service import stock
        item=stock(session,country_id,code)
        if item.quantity+delta<0:raise FinanceError('Brak dostatecznej ilości surowca w magazynie. Złóż w ziemi i ładunków w drodze nie można sprzedawać.')
        item.quantity+=delta


def trade_warehouse(session,country_id):
    from game.mining_service import warehouse
    from game.research_models import ResearchAccount
    result=warehouse(session,country_id)
    account=session.get(ResearchAccount,country_id)
    available=account.ammunition if account else 0
    reserved=sum(cargo.get(AMMUNITION,0) for cargo in session.scalars(select(TradeOffer.cargo).where(TradeOffer.panstwo_id==country_id,TradeOffer.status=='open')))
    result[AMMUNITION]={'available':available,'reserved':reserved,'total':available+reserved}
    from game.governance import army_for_country
    from game.military_service import active_counts
    from game.military_models import MilitaryBase
    from game.commerce_models import ResourceStock
    army=army_for_country(session,country_id)
    active=active_counts(list(session.scalars(select(MilitaryBase).where(MilitaryBase.panstwo_id==country_id))),session,country_id)
    for code in GOODS:
        reserved=sum(cargo.get(code,0) for cargo in session.scalars(select(TradeOffer.cargo).where(TradeOffer.panstwo_id==country_id,TradeOffer.status=='open')))
        if code in ARMY_GOODS:
            field=ARMY_GOODS[code];available=max(0,(getattr(army,field) or 0)-active.get(field,0)) if army else 0
        else:
            row=session.get(ResourceStock,(country_id,code));available=int(row.quantity) if row else 0
        result[code]={'available':available,'reserved':reserved,'total':available+reserved}
    return result
