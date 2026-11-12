"""Persistent rejection guard across analyses in the same authorization revision. Reading identical data is not a reset."""
import hashlib,json
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session
from extensions import db
from game.paga_ai_models import PagaAiLog,PagaAiJob

def retry_state(actor,operation,parameters):
    with Session(db.engine) as session:
        scope=(PagaAiLog.job_id==None) if actor.job_id is None else PagaAiLog.job_id.in_(select(PagaAiJob.id).where(PagaAiJob.revision==actor.revision))
        rows=session.scalars(select(PagaAiLog).where(PagaAiLog.country_id==actor.country_id,scope).order_by(PagaAiLog.id)).all()
        observations={}
        for row in rows:
            if row.validation!='EXECUTED':continue
            if row.operation.endswith(':GET'):
                key=json.dumps([row.operation,row.parameters],sort_keys=True,ensure_ascii=False)
                observations[key]=row.result
            elif row.operation=='game_finance.preview:POST' or (row.operation=='game_infrastructure.roads_change:POST' and row.parameters.get('path',{}).get('operation','').endswith('wycena')):
                from game.paga_ai_observation import scrub
                observations[row.operation+json.dumps(row.parameters.get('path',{}),sort_keys=True)]=scrub(row.result)
            else:observations['last_successful_write']=row.id
        fingerprint=hashlib.sha256(json.dumps(observations,sort_keys=True,default=str).encode()).hexdigest()
        semantic={**parameters,'data':{k:v for k,v in parameters.get('data',{}).items() if k!='rationale'}}
        def canonical(value):
            if type(value) in (int,float):return {'number':str(Decimal(str(value)).normalize())}
            if isinstance(value,dict):return {k:canonical(v) for k,v in value.items()}
            if isinstance(value,list):return [canonical(v) for v in value]
            return value
        command_hash=hashlib.sha256(json.dumps(canonical([operation,semantic]),sort_keys=True).encode()).hexdigest()
        for row in reversed(rows):
            if row.operation==operation and (row.result or {}).get('_retry_command')==command_hash and row.validation=='REJECTED' and (row.result or {}).get('_retry_state')==fingerprint:
                return fingerprint,command_hash,row.reason
        return fingerprint,command_hash,None
