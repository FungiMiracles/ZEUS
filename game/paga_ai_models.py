"""UAT state-player control, isolated identities, durable tasks, write ledger, goals, plans, metrics and audit.

Every row that belongs to a country carries country_id and is only read for that country.
"""
from extensions import db
from game.models import utc_now

class PagaAiControl(db.Model):
    __tablename__='game_paga_ai_control'
    id=db.Column(db.Integer,primary_key=True)
    enabled=db.Column(db.Boolean,nullable=False,default=False)
    revision=db.Column(db.Integer,nullable=False,default=0)
    updated_at=db.Column(db.DateTime,nullable=False,default=utc_now)
    model_id=db.Column(db.String(100),nullable=False,default='Qwen3.5-4B-Q4_K_M')
    event_cursor=db.Column(db.Integer,nullable=False,default=0)
    forum_cursor=db.Column(db.Integer,nullable=False,default=0)
    private_cursor=db.Column(db.Integer,nullable=False,default=0)
    # Guaranteed maximum gap between strategic reviews of one country (real minutes), independent of queue load.
    review_interval_minutes=db.Column(db.Integer,nullable=False,default=180)
    # Upper bound of model calls for one task (decision + corrections).
    max_model_calls=db.Column(db.Integer,nullable=False,default=3)

class PagaAiIdentity(db.Model):
    __tablename__='game_paga_ai_identities'
    country_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),primary_key=True)
    user_id=db.Column(db.Integer,db.ForeignKey('game_users.id'),nullable=False,unique=True)
    memory=db.Column(db.String(2000),nullable=False,default='')
    next_at=db.Column(db.DateTime,nullable=False,default=utc_now)
    # Own notification inbox cursor (same notifications a human player of this country receives).
    notification_cursor=db.Column(db.Integer,nullable=False,default=0)
    last_review_at=db.Column(db.DateTime)
    last_probe_at=db.Column(db.DateTime)
    # Structured strategic memory: decisions, strategies, commitments, notes. Model-written, untrusted data.
    strategy=db.Column(db.JSON)

class PagaAiJob(db.Model):
    """A PAGA task. `trigger` is the semantic deduplication key (meaning + game state), unique per country."""
    __tablename__='game_paga_ai_jobs'
    id=db.Column(db.Integer,primary_key=True)
    country_id=db.Column(db.Integer,nullable=False,index=True)
    priority=db.Column(db.Integer,nullable=False,default=30)
    trigger=db.Column(db.String(100),nullable=False)
    revision=db.Column(db.Integer,nullable=False)
    status=db.Column(db.String(24),nullable=False,default='PENDING',index=True)
    created_at=db.Column(db.DateTime,nullable=False,default=utc_now)
    claimed_at=db.Column(db.DateTime)
    finished_at=db.Column(db.DateTime)
    error=db.Column(db.String(500))
    kind=db.Column(db.String(40),nullable=False,default='legacy',index=True)
    source=db.Column(db.String(40),nullable=False,default='legacy')
    object_ref=db.Column(db.String(100))
    context=db.Column(db.JSON)
    journal=db.Column(db.JSON)
    result=db.Column(db.JSON)
    attempts=db.Column(db.Integer,nullable=False,default=0)
    model_calls=db.Column(db.Integer,nullable=False,default=0)
    retries=db.Column(db.Integer,nullable=False,default=0)
    duration_ms=db.Column(db.Integer)
    not_before=db.Column(db.DateTime)
    expires_at=db.Column(db.DateTime)
    goal_id=db.Column(db.Integer,index=True)
    # PAGA MULTI-AI: the model that holds (or last held) this task: gemini, groq, qwen or zeus (no model call).
    provider=db.Column(db.String(16),index=True)
    __table_args__=(db.UniqueConstraint('country_id','trigger',name='uq_paga_ai_job_trigger'),)

class PagaAiLog(db.Model):
    __tablename__='game_paga_ai_logs'
    id=db.Column(db.Integer,primary_key=True)
    job_id=db.Column(db.Integer,db.ForeignKey('game_paga_ai_jobs.id'),index=True)
    country_id=db.Column(db.Integer,nullable=False,index=True)
    game_at=db.Column(db.DateTime,nullable=False)
    real_at=db.Column(db.DateTime,nullable=False,default=utc_now)
    operation=db.Column(db.String(150),nullable=False)
    parameters=db.Column(db.JSON,nullable=False)
    validation=db.Column(db.String(30),nullable=False)
    result=db.Column(db.JSON)
    reason=db.Column(db.String(500))
    model_id=db.Column(db.String(100),nullable=False)

class PagaAiWrite(db.Model):
    """Write-ahead ledger: one row per (task, decision) BEFORE a state-changing call; never executed twice."""
    __tablename__='game_paga_ai_writes'
    id=db.Column(db.Integer,primary_key=True)
    job_id=db.Column(db.Integer,nullable=False,index=True)
    country_id=db.Column(db.Integer,nullable=False,index=True)
    operation=db.Column(db.String(150),nullable=False)
    decision_hash=db.Column(db.String(64),nullable=False)
    request_id=db.Column(db.String(64),nullable=False,unique=True)
    status=db.Column(db.String(16),nullable=False,default='PENDING')  # PENDING, DONE, REJECTED, UNKNOWN
    created_at=db.Column(db.DateTime,nullable=False,default=utc_now)
    finished_at=db.Column(db.DateTime)
    log_id=db.Column(db.Integer)
    __table_args__=(db.UniqueConstraint('job_id','decision_hash',name='uq_paga_ai_write_decision'),)

class PagaAiGoal(db.Model):
    """Model-owned long-term goal; ZEUS only monitors it. parent_id allows decomposition into smaller intentions."""
    __tablename__='game_paga_ai_goals'
    id=db.Column(db.Integer,primary_key=True)
    country_id=db.Column(db.Integer,nullable=False,index=True)
    parent_id=db.Column(db.Integer)
    title=db.Column(db.String(120),nullable=False)
    description=db.Column(db.String(600),nullable=False,default='')
    priority=db.Column(db.Integer,nullable=False,default=3)  # 1 most important … 5 least
    status=db.Column(db.String(16),nullable=False,default='ACTIVE')  # ACTIVE, SUSPENDED, ABANDONED, ACHIEVED
    criteria=db.Column(db.JSON)
    progress=db.Column(db.JSON)
    note=db.Column(db.String(300))
    created_at=db.Column(db.DateTime,nullable=False,default=utc_now)
    created_game_at=db.Column(db.DateTime)
    updated_at=db.Column(db.DateTime,nullable=False,default=utc_now)

class PagaAiPlan(db.Model):
    """INTENT: a future decision point created by the model (fires a task; the model still decides).
    CONDITIONAL: a concrete pre-authorised operation executed once when its whitelisted condition occurs."""
    __tablename__='game_paga_ai_plans'
    id=db.Column(db.Integer,primary_key=True)
    country_id=db.Column(db.Integer,nullable=False,index=True)
    goal_id=db.Column(db.Integer)
    kind=db.Column(db.String(16),nullable=False)
    condition=db.Column(db.JSON,nullable=False)
    operation=db.Column(db.JSON)
    note=db.Column(db.String(300),nullable=False,default='')
    status=db.Column(db.String(16),nullable=False,default='ACTIVE',index=True)  # ACTIVE, FIRED, EXPIRED, CANCELLED
    revision=db.Column(db.Integer,nullable=False)
    created_at=db.Column(db.DateTime,nullable=False,default=utc_now)
    expires_game_at=db.Column(db.DateTime,nullable=False)
    fired_at=db.Column(db.DateTime)
    result=db.Column(db.JSON)

class PagaAiMetric(db.Model):
    """One row per model call or per finished task (call=False)."""
    __tablename__='game_paga_ai_metrics'
    id=db.Column(db.Integer,primary_key=True)
    job_id=db.Column(db.Integer,index=True)
    country_id=db.Column(db.Integer,nullable=False,index=True)
    kind=db.Column(db.String(40),nullable=False)
    is_call=db.Column(db.Boolean,nullable=False,default=True)
    created_at=db.Column(db.DateTime,nullable=False,default=utc_now,index=True)
    context_ms=db.Column(db.Integer)
    prompt_tokens=db.Column(db.Integer)
    prompt_ms=db.Column(db.Integer)
    generated_tokens=db.Column(db.Integer)
    generation_ms=db.Column(db.Integer)
    total_ms=db.Column(db.Integer)
    peak_rss_bytes=db.Column(db.BigInteger)
    outcome=db.Column(db.String(24),nullable=False)
    detail=db.Column(db.JSON)
    # PAGA MULTI-AI call log: provider, exact model, wall-clock start/end and the ZEUS validation result.
    provider=db.Column(db.String(16),index=True)
    model_name=db.Column(db.String(100))
    started_at=db.Column(db.DateTime)
    finished_at=db.Column(db.DateTime)
    validation=db.Column(db.String(24))


class PagaAiProvider(db.Model):
    """Provider-wide pause after a rate limit or an outage (no keys or secrets are stored here)."""
    __tablename__='game_paga_ai_providers'
    provider=db.Column(db.String(64),primary_key=True)   # 'gemini' or a model key 'gemini:<model>' (per-model quotas)
    cooldown_until=db.Column(db.DateTime)
    last_error=db.Column(db.String(300))
    updated_at=db.Column(db.DateTime,nullable=False,default=utc_now)

ACTIVE_STATUSES=('PENDING','RUNNING','BLOCKED','QUEUED')
FINAL_STATUSES=('COMPLETED','FAILED','CANCELLED','SUPERSEDED','FINISHED','INTERRUPTED')
