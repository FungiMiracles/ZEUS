"""Operational metrics of PAGA AI for the administrator panel (no model calls, aggregate queries only)."""
from datetime import timedelta
from sqlalchemy import select,func
from game.paga_ai_models import PagaAiMetric,PagaAiJob
from game.paga_ai_tasks import now


def summary(session,hours=24):
    since=now()-timedelta(hours=hours)
    tasks=session.execute(select(PagaAiMetric.outcome,func.count(),func.avg(PagaAiMetric.total_ms)).where(PagaAiMetric.is_call.is_(False),PagaAiMetric.created_at>=since).group_by(PagaAiMetric.outcome)).all()
    calls=session.execute(select(PagaAiMetric.outcome,func.count(),func.avg(PagaAiMetric.total_ms),func.avg(PagaAiMetric.prompt_tokens),func.avg(PagaAiMetric.generated_tokens),
                                 func.avg(PagaAiMetric.prompt_ms),func.avg(PagaAiMetric.generation_ms),func.max(PagaAiMetric.peak_rss_bytes),func.avg(PagaAiMetric.context_ms))
                          .where(PagaAiMetric.is_call.is_(True),PagaAiMetric.created_at>=since).group_by(PagaAiMetric.outcome)).all()
    finished=session.execute(select(func.count(),func.avg(PagaAiJob.model_calls),func.sum(PagaAiJob.retries),func.avg(PagaAiJob.duration_ms))
                             .where(PagaAiJob.finished_at>=since,PagaAiJob.duration_ms.is_not(None))).one()
    def number(value,digits=0):return None if value is None else round(float(value),digits)
    call_rows={outcome:{'count':count,'avg_ms':number(avg_ms),'avg_prompt_tokens':number(prompt),'avg_generated_tokens':number(generated),
                        'avg_prompt_ms':number(prompt_ms),'avg_generation_ms':number(generation_ms),'peak_rss_bytes':peak,'avg_context_ms':number(context_ms)}
               for outcome,count,avg_ms,prompt,generated,prompt_ms,generation_ms,peak,context_ms in calls}
    task_rows={outcome:{'count':count,'avg_ms':number(avg_ms)} for outcome,count,avg_ms in tasks}
    return {'hours':hours,'tasks':task_rows,'calls':call_rows,
            'tasks_finished':finished[0],'avg_model_calls_per_task':number(finished[1],2),'retries':int(finished[2] or 0),'avg_task_ms':number(finished[3]),
            'completed':sum(row['count'] for key,row in task_rows.items() if key in ('COMPLETED','ALREADY_DONE')),
            'failed':sum(row['count'] for key,row in task_rows.items() if key in ('FAILED','MODEL_ERROR')),
            'timeouts':sum(row['count'] for key,row in call_rows.items() if key=='TIMEOUT')}
