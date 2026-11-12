from flask_sqlalchemy import SQLAlchemy
from flask_sqlalchemy.query import Query
from flask_sqlalchemy.session import Session


def _visible(instance, execution_options=None):
    # get() can return an identity-map entry without executing a SELECT.
    from models import Panstwo
    if (isinstance(instance, Panstwo) and instance.status == 'usunięte'
            and not (execution_options or {}).get('include_deleted_countries')):
        return None
    return instance


class CountrySession(Session):
    def get(self, entity, ident, **kwargs):
        return _visible(super().get(entity, ident, **kwargs), kwargs.get('execution_options'))


class CountryQuery(Query):
    def get(self, ident):
        return _visible(super().get(ident), self._execution_options)


db = SQLAlchemy(query_class=CountryQuery, session_options={'class_': CountrySession})
