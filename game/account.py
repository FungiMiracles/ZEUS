"""Credential erasure and transactional handover; historical records retain their author ID."""
from datetime import timedelta
from hashlib import sha256
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for
from sqlalchemy import select
from sqlalchemy.orm import Session,lazyload
from werkzeug.security import check_password_hash
from extensions import db
from models import Panstwo
from game.models import GameUser, GamePlayerCountry, utc_now
from game.forum import validate_csrf

account_bp=Blueprint('game_account',__name__,url_prefix='/game/konto')


class AccountDeletionError(ValueError):pass


def delete_account(database,user_id,password):
    if current_app.config.get('ENV_NAME')!='UAT':
        raise AccountDeletionError('Usuwanie kont jest dostępne wyłącznie w UAT.')
    country_id=database.scalar(select(GamePlayerCountry.panstwo_id).where(GamePlayerCountry.user_id==user_id))
    # The same country lock protects registration, PAGA changes and autonomous decisions.
    if country_id is not None:
        database.scalar(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID==country_id).with_for_update())
    user=database.scalar(select(GameUser).where(GameUser.id==user_id).with_for_update().execution_options(populate_existing=True))
    if user is None or not user.is_active:raise AccountDeletionError('Konto nie jest aktywne. Zaloguj się ponownie.')
    if not isinstance(password,str) or not 1<=len(password)<=128 or not user.password_hash or not check_password_hash(user.password_hash,password):
        raise AccountDeletionError('Nieprawidłowe hasło. Konto nie zostało usunięte.')
    assignment=database.scalar(select(GamePlayerCountry).where(GamePlayerCountry.user_id==user_id).with_for_update().execution_options(populate_existing=True))
    if (assignment.panstwo_id if assignment else None)!=country_id:
        raise AccountDeletionError('Przypisanie państwa zmieniło się. Odśwież stronę.')
    if assignment is not None:database.delete(assignment)
    # Keep the historical identity solely for foreign keys, forum attribution and past decisions.
    user.email=None;user.email_normalized=None;user.password_hash=None
    user.email_verified_at=None;user.is_active=False
    database.flush()
    autonomous=False
    if country_id is not None and current_app.config.get('PAGA_ENABLED'):
        from game.paga import PagaConfiguration,PagaRevision
        from game.autonomy_models import AutonomySchedule
        from game.diplomacy_models import DiplomaticAction
        from game.finance_service import game_now
        config=database.scalar(select(PagaConfiguration).where(PagaConfiguration.panstwo_id==country_id).with_for_update().execution_options(populate_existing=True))
        # PAGA2: profil państwa jest źródłem flagi autonomii — przekazanie włącza ją także tam (lub tworzy profil z konfiguracji PAGA).
        from game.paga2.models import Paga2Profile,Paga2ProfileRevision,migrated_profile,table_ready
        if table_ready(database,Paga2Profile):
            profile=database.get(Paga2Profile,country_id,with_for_update=True,populate_existing=True)
            at=utc_now().replace(tzinfo=None);actor='Przekazanie po usunięciu konta'
            if profile is None and config and config.approved_at:
                data=migrated_profile(config)
                profile=Paga2Profile(panstwo_id=country_id,categories=data['categories'],priorities=data['priorities'],traits=data['traits'],
                                     autonomy_enabled=False,source='migrated',revision=0,updated_at=at,actor=actor)
                database.add(profile)
            if profile is not None:
                autonomous=True
                if not profile.autonomy_enabled:
                    profile.autonomy_enabled=True;profile.revision+=1;profile.updated_at=at;profile.actor=actor
                    database.add(Paga2ProfileRevision(panstwo_id=country_id,revision=profile.revision,actor=actor,created_at=at,
                        configuration={'categories':profile.categories,'priorities':profile.priorities,'traits':profile.traits,'autonomyEnabled':True,'handover':True}))
        if config and config.approved_at:
            autonomous=True
            if not config.autonomy_enabled:
                at=utc_now().replace(tzinfo=None);actor='Przekazanie po usunięciu konta'
                config.autonomy_enabled=True;config.revision+=1;config.updated_at=at;config.actor=actor
                database.add(PagaRevision(panstwo_id=country_id,revision=config.revision,mode='handover',configuration={'character':config.approved_character,'interests':config.approved_interests,'autonomyEnabled':True},actor=actor,created_at=at))
            now=game_now()
            schedule=database.get(AutonomySchedule,country_id)
            if schedule is None or schedule.next_at>now+timedelta(days=1):
                next_at=now+timedelta(seconds=int(sha256(f'autonomy:{country_id}'.encode()).hexdigest()[:12],16)%86400)
                if schedule is None:database.add(AutonomySchedule(country_id=country_id,next_at=next_at))
                else:schedule.next_at=next_at
        # Pending offers belong to the departing player; retain them as expired history.
        for proposal in database.scalars(select(DiplomaticAction).where(DiplomaticAction.status=='PENDING',((DiplomaticAction.sender_user_id==user_id)|(DiplomaticAction.recipient_user_id==user_id))).with_for_update()):
            proposal.status='EXPIRED';proposal.decided_at=utc_now()
    database.flush()
    return autonomous


@account_bp.route('/usun',methods=['GET','POST'])
def remove():
    if current_app.config.get('ENV_NAME')!='UAT':abort(404)
    user_id=session.get('game_user_id')
    user=db.session.get(GameUser,user_id) if type(user_id) is int else None
    if user is None or not user.is_active:
        session.pop('game_user_id',None)
        return redirect(url_for('wejscie'),code=303)
    error=None
    confirmed=request.args.get('confirm')=='1'
    if request.method=='POST':
        validate_csrf();confirmed=True
        try:
            with Session(db.engine) as database,database.begin():
                delete_account(database,user_id,request.form.get('password',''))
        except AccountDeletionError as exception:error=str(exception)
        except Exception:
            current_app.logger.exception('Nie udało się usunąć konta gry (użytkownik %s)',user_id)
            error='Nie udało się usunąć konta. Spróbuj ponownie.'
        else:
            for key in ('game_user_id','game_csrf_token','game_registration_csrf'):session.pop(key,None)
            flash('Konto zostało usunięte.','game_success')
            return redirect(url_for('wejscie'),code=303)
    from game.country_summary import country_summary
    assignment=user.country_assignment
    country=db.session.scalar(select(Panstwo).where(Panstwo.PANSTWO_ID==assignment.panstwo_id).options(lazyload('*'))) if assignment else None
    return render_template('game/account_delete.html',game_user=user,game_country=country_summary(country),confirmed=confirmed,error=error),400 if error else 200
