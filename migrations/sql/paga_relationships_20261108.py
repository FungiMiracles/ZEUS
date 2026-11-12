"""Add UAT-only soft diplomatic preferences; preserve all current game relations."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
assert ROOT == Path('/home/oskar_zeus_admin/ZEUS_UAT')
sys.path.insert(0, str(ROOT))


def migrate():
    from scripts.paga_ai_admin import make_app
    from extensions import db
    from game.paga_relationships import PagaRelationship, PagaRelationshipRevision
    app = make_app()  # Asserts UAT database; starts no background schedulers.
    with app.app_context():
        for model in (PagaRelationship, PagaRelationshipRevision):
            model.__table__.create(db.engine, checkfirst=True)
    print('UAT diplomatic preference tables ready. No country relations or AI switches changed.')


if __name__ == '__main__':
    migrate()
