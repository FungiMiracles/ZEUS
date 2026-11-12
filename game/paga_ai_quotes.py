"""Recover concurrency/quote fields from the actor's own reviewed player responses."""
from sqlalchemy import select
from sqlalchemy.orm import Session
from extensions import db
from game.paga_ai_models import PagaAiLog


def reviewed(actor,operation,*,path=None,decision=None):
    with Session(db.engine) as session:
        rows=session.scalars(select(PagaAiLog).where(PagaAiLog.country_id==actor.country_id,
            PagaAiLog.job_id==actor.job_id,PagaAiLog.operation==operation).order_by(PagaAiLog.id.desc())).all()
        for row in rows:
            if path is not None and row.parameters.get('path')!=path:continue
            if row.validation!='EXECUTED':raise ValueError('Ostatni odczyt/wycena nie powiódł się. Odczytaj stan lub ponów poprawną wycenę.')
            if decision is not None and {k:v for k,v in row.parameters.get('data',{}).items() if k!='rationale'}!=decision:
                raise ValueError('Decyzja różni się od ostatniej wyceny. Najpierw wyceń poprawiony plan.')
            return row.result['result']
    raise ValueError('Najpierw odczytaj stan lub wykonaj wycenę tej decyzji. ZEUS uzupełni pola techniczne z obejrzanego wyniku.')


def prepare(actor,operation,path,data):
    payload=dict(data)
    if operation=='game_finance.transfer:POST' and 'budget_id' not in payload:
        state=reviewed(actor,'game_finance.page:GET').get('state') or {}
        if not state.get('approved') or type(state.get('budget_id')) is not int:
            raise ValueError('Bieżący budżet nie jest zatwierdzony. Zdecyduj o budget.plan przed przesunięciem środków.')
        payload['budget_id']=state['budget_id']
    if operation=='game_messages.send:POST' and type(data.get('reply_to_id')) is int and 'recipient_id' not in data:
        # A reply can only go to the sender of the answered message (game rule): a technical field ZEUS fills in.
        from game.communication_models import PrivateMessage
        from game.paga_ai_models import PagaAiIdentity
        with Session(db.engine) as session:
            identity=session.get(PagaAiIdentity,actor.country_id)
            source=session.get(PrivateMessage,data['reply_to_id'])
            if identity is not None and source is not None and source.recipient_user_id==identity.user_id:payload['recipient_id']=source.sender_user_id
    if operation=='game_intelligence.change:POST' and data.get('action')=='counter_upgrade':
        if 'expected_level' in data:raise ValueError('Poziom techniczny pobiera ZEUS. Najpierw odczytaj game_intelligence.state:GET.')
        payload['expected_level']=reviewed(actor,'game_intelligence.state:GET')['counterLevel']
    if operation=='game_forum.edit:POST':
        if 'version' in data:raise ValueError('Wersję wpisu pobiera ZEUS. Najpierw odczytaj game_forum.edit:GET dla tego wpisu.')
        state=reviewed(actor,'game_forum.edit:GET',path=path)
        versions=[field['value'] for form in state.get('forms',[]) for field in form['fields'] if field.get('name')=='version']
        if not versions:raise ValueError('Nie znaleziono wersji własnego wpisu. Odczytaj formularz edycji ponownie.')
        payload['version']=versions[-1]
    if operation=='game_research.change:POST' and data.get('action')=='buy':
        if 'expected_point_price' in data:raise ValueError('Nie podawaj technicznej ceny. Odczytaj game_research.state:GET przed zakupem.')
        state=reviewed(actor,'game_research.state:GET')
        payload['expected_point_price']=state['pointPrice']
    if operation=='game_infrastructure.roads_change:POST':
        kind=path.get('operation')
        quote_kind={'buduj':'wycena','ulepsz':'ulepsz-wycena'}.get(kind)
        if kind=='decyzja' and data.get('decision')=='border':quote_kind='granica-wycena'
        if quote_kind:
            if 'expected_cost' in data:raise ValueError('Koszt techniczny pobiera ZEUS z ostatniej wyceny. Nie generuj expected_cost.')
            decision={k:v for k,v in data.items() if k not in ('rationale','decision')}
            quote=reviewed(actor,operation,path={'operation':quote_kind},decision=decision)['quote']
            payload['expected_cost']=quote['cost']
            if kind=='buduj':payload['path']=quote['path']
    return payload
