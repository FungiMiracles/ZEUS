"""Procenty wieku i całkowite liczby osób z metodą największych reszt."""
from decimal import Decimal,ROUND_DOWN,localcontext
from sqlalchemy import select
from sqlalchemy.orm import lazyload
from extensions import db
from models import Panstwo
from game.finance_service import FinanceError,decimal_value
from game.models import utc_now


class PopulationStructure(db.Model):
    __tablename__='country_population_structures'
    panstwo_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),primary_key=True)
    children=db.Column(db.Numeric(5,2),nullable=False)
    working=db.Column(db.Numeric(5,2),nullable=False)
    seniors=db.Column(db.Numeric(5,2),nullable=False)
    version=db.Column(db.Integer,nullable=False,default=1)
    updated_at=db.Column(db.DateTime,nullable=False,default=utc_now)
    actor=db.Column(db.String(120),nullable=False)
    __table_args__=(db.CheckConstraint('children>=0 AND working>=0 AND seniors>=0 AND children+working+seniors=100',name='ck_population_structure'),{'mysql_engine':'InnoDB'})


def structure_data(session,country_id):
    country=session.scalar(select(Panstwo).options(lazyload('*')).where(Panstwo.PANSTWO_ID==country_id))
    if country is None:raise FinanceError('Nie znaleziono państwa.')
    row=session.get(PopulationStructure,country_id);population=country.panstwo_populacja
    data={'countryId':country_id,'name':country.panstwo_nazwa,'population':population,'version':row.version if row else 0,'groups':[]}
    if row is None:return data
    shares=[row.children,row.working,row.seniors];counts=[None]*3
    if population is not None:
        with localcontext() as context:
            context.prec=64
            exact=[Decimal(population)*share/100 for share in shares];counts=[int(n.to_integral_value(rounding=ROUND_DOWN)) for n in exact]
            for i in sorted(range(3),key=lambda i:(-(exact[i]-counts[i]),i))[:population-sum(counts)]:counts[i]+=1
    data['groups']=[{'key':key,'label':label,'percent':str(share),'count':count} for key,label,share,count in zip(('children','working','seniors'),('0–17 lat','18–64 lata','65+ lat'),shares,counts)]
    return data


def save_structure(session,country_id,data,actor):
    shares=[decimal_value(data.get(key),label) for key,label in [('children','Wiek 0–17'),('working','Wiek 18–64'),('seniors','Wiek 65+')]]
    if any(n<0 or n>100 or n.quantize(Decimal('.01'))!=n for n in shares) or sum(shares)!=100:raise FinanceError('Podaj procenty z najwyżej dwoma miejscami po przecinku, sumujące się do 100%.')
    if session.scalar(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID==country_id).with_for_update()) is None:raise FinanceError('Nie znaleziono państwa.')
    row=session.get(PopulationStructure,country_id)
    if type(data.get('version')) is not int or data['version']!=(row.version if row else 0):raise FinanceError('Dane zmieniły się. Odśwież formularz.')
    if row is None:row=PopulationStructure(panstwo_id=country_id,version=0);session.add(row)
    row.children,row.working,row.seniors=shares;row.version+=1;row.actor=actor;row.updated_at=utc_now();session.flush()
    return structure_data(session,country_id)
