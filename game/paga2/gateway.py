"""Bramka PAGA2 do ekranów i operacji gracza.

PAGA2 nie czyta bazy cudzych państw bezpośrednio: każdy odczyt i każda operacja przechodzi przez
oryginalny endpoint gracza wywołany jako techniczna tożsamość państwa. Dzięki temu obowiązują
te same reguły, uprawnienia i ta sama widoczność informacji co dla gracza ludzkiego (punkty g i h).
"""
import secrets
from datetime import date,datetime
from decimal import Decimal
from flask import template_rendered
from sqlalchemy import select
from game.paga_ai_actor import AiActor,acting,ensure_identity,AiPermissionError
from game.paga2.models import Paga2Control

# Rekordy jawnych tabel, które ekrany gracza pokazują wszystkim (np. panel wydarzeń); bez kolumn technicznych.
PUBLIC_TABLES={'zdarzenia':{'payload_json','effect_applied','data_rzeczywista','created_at'}}

# Odczyty, które w grze są wywołaniem POST bez skutków (podgląd planu budżetu).
READ_ONLY_POST={'/game/finanse/podglad'}


class GatewayError(RuntimeError):
    def __init__(self,status,message,data=None):
        super().__init__(message);self.status=status;self.data=data


def actor_for(session,country_id,*,view=False):
    """Tożsamość PAGA2 państwa. view=True: wyłącznie odczyt (np. podgląd w panelu przy wyłączonym PAGA2)."""
    identity=ensure_identity(session,country_id)
    control=session.get(Paga2Control,1)
    if control is None:raise AiPermissionError('Brak konfiguracji PAGA2. Wykonaj migrację UAT.')
    return AiActor(country_id=country_id,user_id=identity.user_id,revision=control.revision,engine='paga2_view' if view else 'paga2')


def plain(value,depth=0,own=frozenset()):
    """Tylko dane proste: słowniki, listy, liczby, tekst. Obiekty ORM i inne typy są pomijane."""
    if depth>12:return None
    if value is None or type(value) in (str,int,float,bool):return value
    if isinstance(value,Decimal):return float(value)
    if isinstance(value,(datetime,date)):return value.isoformat()
    if isinstance(value,dict):
        result={}
        for key,item in value.items():
            converted=plain(item,depth+1,own)
            if converted is not None or item is None:result[str(key)]=converted
        return result
    if isinstance(value,(list,tuple,set)):return [plain(item,depth+1,own) for item in value]
    if hasattr(value,'_mapping') and hasattr(value,'_fields'):  # wiersz zapytania SQLAlchemy (Row)
        return [plain(item,depth+1,own) for item in value]
    table=getattr(value,'__table__',None)
    if table is not None and table.name in PUBLIC_TABLES:
        return {column.key:plain(getattr(value,column.key,None),depth+1,own) for column in table.columns if column.key not in PUBLIC_TABLES[table.name]}
    if table is not None and table.name in own:  # własne rekordy państwa pokazywane na jego ekranie (np. armia)
        return {column.key:plain(getattr(value,column.key,None),depth+1,own) for column in table.columns}
    return None


def call(app,actor,path,*,method='GET',query=None,json=None,form=None,keep=None,own=frozenset()):
    """Wywołuje endpoint gracza. Zwraca (status, dane). keep: klucze kontekstu szablonu do zachowania dla stron HTML."""
    if not path.startswith('/game/'):raise GatewayError(400,'Ścieżka poza grą.')
    if actor.engine=='paga2_view' and method!='GET' and path not in READ_ONLY_POST:raise GatewayError(403,'Tryb podglądu nie wykonuje operacji.')
    token=secrets.token_urlsafe(32);captured={}
    def rendered(sender,template,context,**extra):
        from game.paga_ai_actor import current_actor
        if current_actor()!=actor:return
        for key in (keep or ()):
            if key in context:captured[key]=plain(context[key],own=own)
        if isinstance(context.get('error'),str):captured['error']=context['error']
    with acting(actor),app.test_client() as client:
        with client.session_transaction() as browser:
            browser['game_user_id']=actor.user_id;browser['game_csrf_token']=token
        kwargs={'headers':{'X-CSRF-Token':token},'follow_redirects':False}
        if query:kwargs['query_string']=query
        if json is not None:kwargs['json']=json
        if form is not None:kwargs['data']={**form,'csrf_token':token}
        with template_rendered.connected_to(rendered,app):
            response=client.open(path,method=method,**kwargs)
    status=response.status_code
    if response.is_json:data=response.get_json()
    elif 300<=status<400:data={'redirect':response.headers.get('Location')}
    else:data=captured
    return status,data
