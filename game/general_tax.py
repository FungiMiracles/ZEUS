from game.paga_ai_actor import country_user_id
"""ZEUS-GAME-0005: tax basis snapshots, annual revenue and tax penalties."""
from decimal import Decimal,localcontext,ROUND_HALF_UP
from sqlalchemy import select
from sqlalchemy.orm import lazyload
from models import Region,Spoleczenstwo,Gospodarka
from game.finance_service import FinanceError
from game.population_structure import structure_data
from game.governance import controlled_ids,economy


def capture_basis(session,country_id):
    age=structure_data(session,country_id)
    working=next((group['count'] for group in age['groups'] if group['key']=='working'),None)
    if working is None:raise FinanceError('Administrator musi najpierw ustalić strukturę wieku ludności tego państwa w WIKI.')
    rows=session.execute(select(Region.region_polozenie_id,Region.region_stan_infra_drogowej,Region.region_stan_infra_kolejowej,Region.region_stan_infra_energetycznej,Region.region_stan_infra_mieszkalnej,Region.region_stan_infra_portowej).where(Region.panstwo_id.in_(controlled_ids(session,country_id)))).all()
    values=[Decimal(value) for row in rows for i,value in enumerate(row[1:]) if value is not None and 0<=value<=100 and (i!=4 or row[0] not in (None,1))]
    if not values:raise FinanceError('Brak danych rozwoju infrastruktury potrzebnych do obliczenia podatku ogólnego.')
    fields=(Spoleczenstwo.zadowolenie_spoleczne,Spoleczenstwo.stabilnosc_spoleczna,Spoleczenstwo.poziom_edukacji,Spoleczenstwo.zdrowie_publiczne,Spoleczenstwo.przestepczosc,Spoleczenstwo.zaufanie_do_wladzy)
    social=session.execute(select(*fields).where(Spoleczenstwo.panstwo_id==country_id)).one_or_none()
    if social is None or any(value is None or not 0<=value<=100 for value in social):raise FinanceError('Brak kompletnych wskaźników społecznych potrzebnych do obliczenia podatku i jego skutków.')
    unemployment=session.scalar(select(Gospodarka.bezrobocie).where(Gospodarka.panstwo_id==country_id))
    if unemployment is None or not 0<=unemployment<=100:raise FinanceError('Uzupełnij stopę bezrobocia w gospodarce państwa (0–100%).')
    country=economy(session,country_id)
    if country['gdp'] is None or country['population'] is None or country['population']<=0:raise FinanceError('Brak PKB lub ludności do obliczenia PKB per capita.')
    with localcontext() as context:
        context.prec=64
        infrastructure=sum(values)/len(values)
        per_capita=Decimal(country['gdp'])/Decimal(country['population'])
    return {'algorithm_version':5,'working_population':working,'gdp_per_capita':str(per_capita),'unemployment_percent':str(unemployment),'infrastructure':str(infrastructure),'satisfaction':social[0],'stability':social[1],'education':social[2],'public_health':social[3],'crime':social[4],'trust':social[5]}


def annual_revenue(basis,rate):
    with localcontext() as context:
        context.prec=64
        employed=Decimal(basis['working_population'])*(1-Decimal(basis['unemployment_percent'])/100)
        taxable=Decimal(basis['gdp_per_capita'])*employed*rate/100
        bonus=sum((Decimal(basis[key]) for key in ('stability','satisfaction','education','infrastructure','public_health')),Decimal(0))-Decimal(basis['crime'])
        components={'employed_population':str(employed),'tax_before_bonus':str(taxable),'bonus_percent':str(bonus/100),'social_bonus':str(taxable*bonus/10000)}
        total=taxable*(1+bonus/10000)
        return total.quantize(Decimal('.00000001'),rounding=ROUND_HALF_UP),components


def tax_penalty(basis,rate):
    """Round a positive loss half up; nonpositive values never grant a bonus."""
    with localcontext() as context:
        context.prec=64
        if rate<=20:return 0
        loss=(rate-20)/10-(Decimal(basis['trust'])+Decimal(basis['satisfaction']))/100
        return int(max(Decimal(0),loss).quantize(Decimal('1'),rounding=ROUND_HALF_UP))


def apply_tax_penalty(session,country_id,basis,rate,now):
    loss=tax_penalty(basis,rate)
    if not loss:return {'penalty':0,'changes':{}}
    social=session.scalar(select(Spoleczenstwo).options(lazyload('*')).where(Spoleczenstwo.panstwo_id==country_id).with_for_update())
    if social is None:raise FinanceError('Brak wskaźników społecznych do rozliczenia podatku.')
    changes={}
    for field in ('zadowolenie_spoleczne','stabilnosc_spoleczna','zaufanie_do_wladzy'):
        old=getattr(social,field)
        if old is None:raise FinanceError('Niekompletne wskaźniki społeczne do rozliczenia podatku.')
        new=max(0,old-loss);setattr(social,field,new);changes[field]=new-old
    if any(changes.values()):
        from game.models import GamePlayerCountry
        from game.forum_models import GameNotification
        owner=country_user_id(session,country_id)
        if owner is not None:
            message=f"Obywatele nie są zadowoleni z wysokiej stawki podatku. Zaufanie do władzy: {changes['zaufanie_do_wladzy']}, zadowolenie społeczne: {changes['zadowolenie_spoleczne']}"
            session.add(GameNotification(user_id=owner,notification_type='SYSTEM',system_text=message,created_at=now))
    return {'penalty':loss,'changes':changes}
