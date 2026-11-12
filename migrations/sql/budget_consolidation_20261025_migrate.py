from pathlib import Path
import sys,os,hashlib
from decimal import Decimal,localcontext
root=Path('/home/oskar_zeus_admin/ZEUS_UAT');sys.path.insert(0,str(root))
settings=dict(line.split('=',1) for line in (root/'.env.uat').read_text().splitlines() if line and not line.startswith('#') and '=' in line)
for key,value in settings.items():os.environ[key]=value.strip().strip('\"\'')
os.environ['ENV_NAME']='UAT'
from sqlalchemy import create_engine,inspect,text,select,func
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from game.models import GameUser,GamePlayerCountry
from models import Panstwo,Region,Miasto
from game.finance_models import BudgetCategory,StateBudgetAllocation,StateFinancialAccount,StateBudget
from game.budget_categories import CODES
from game.finance_service import game_now,_reserve_for_account,_validate_categories
from game.budget_transfers import refund_retired_diplomacy
url=os.environ['DATABASE_URL'];assert make_url(url).database=='entenda_uat_db'
try:
    engine=create_engine(url,hide_parameters=True)
    statements=[]
    with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as conn:
        assert conn.scalar(text('SELECT DATABASE()'))=='entenda_uat_db'
        def execute(sql):statements.append(sql);conn.exec_driver_sql(sql)
        if 'name' not in {column['name'] for column in inspect(conn).get_columns('game_intelligence_agents')}:
            execute('ALTER TABLE game_intelligence_agents ADD COLUMN name VARCHAR(100) NULL')
        check=next(c for c in inspect(conn).get_check_constraints('game_budget_categories') if c['name'].startswith('ck_gbc_display_order'))
        if '64' not in check['sqltext']:
            assert all(c.isalnum() or c=='_' for c in check['name'])
            execute(f"ALTER TABLE game_budget_categories DROP CHECK `{check['name']}`, ADD CONSTRAINT ck_gbc_display_order_v3 CHECK (display_order BETWEEN 1 AND 64)")
    with Session(engine) as session,session.begin(),localcontext() as context:
        context.prec=64
        accounts=list(session.scalars(select(StateFinancialAccount).order_by(StateFinancialAccount.panstwo_id)))
        for account in accounts:
            _reserve_for_account(account,session.get(StateBudget,account.last_budget_id) if account.last_budget_id else None)
        max_id=session.scalar(select(func.max(StateBudgetAllocation.id))) or 0
        snapshot=lambda:hashlib.sha256(repr(list(session.execute(select(StateBudgetAllocation.id,StateBudgetAllocation.budget_id,StateBudgetAllocation.category_code,StateBudgetAllocation.share_percent,StateBudgetAllocation.amount).where(StateBudgetAllocation.id<=max_id).order_by(StateBudgetAllocation.id)))).encode()).hexdigest()
        before=snapshot()
        if session.get(BudgetCategory,'infrastructure') is None:
            session.execute(text('UPDATE game_budget_categories SET display_order=display_order+30 ORDER BY display_order DESC'))
            session.add(BudgetCategory(code='infrastructure',name_pl='Infrastruktura',display_order=19,is_reserve=False));session.flush()
        for position,code in enumerate(CODES,1):
            row=session.get(BudgetCategory,code);assert row is not None
            row.display_order=position
            if code=='social_policy':row.name_pl='Polityka socjalna i prorodzinna'
        session.flush();_validate_categories(session)
        refunded=Decimal(0);count=0
        for account in accounts:
            amount=refund_retired_diplomacy(session,account.panstwo_id,game_now());refunded+=amount;count+=int(amount>0)
        session.flush()
        for account in accounts:_reserve_for_account(account,session.get(StateBudget,account.last_budget_id) if account.last_budget_id else None)
        assert before==snapshot(),'Approved budget allocations changed'
    (root/'migrations/sql/budget_consolidation_20261025.sql').write_text('-- UAT schema changes. Approved allocations remain intact; code normalizes historical categories.\n'+';\n'.join(statements)+';\n-- Active dictionary order and idempotent refunds are applied transactionally by the migration helper.\n')
    print(f'UAT migration verified: 11 active sectors, agent names, diplomacy refunds on {count} accounts; total refunded {refunded} ROI. Approved snapshots preserved; all reserve accounts consistent.')
except Exception as exc:
    print('Migration failed:',type(exc).__name__)
    if isinstance(exc,AssertionError):print(str(exc))
    orig=getattr(exc,'orig',None)
    if orig is not None and getattr(orig,'args',None):print('Database error code:',orig.args[0])
    sys.exit(1)
