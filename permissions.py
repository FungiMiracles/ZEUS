# permissions.py
from flask import session, abort


def aktualna_rola():
    return session.get("rola")


def ma_role(*dozwolone):
    return session.get("rola") in dozwolone


def wymaga_roli(*dozwolone):
    def decorator(fn):
        def wrapper(*args, **kwargs):
            if session.get("rola") not in dozwolone:
                abort(403)
            return fn(*args, **kwargs)
        wrapper.__name__ = fn.__name__
        return wrapper
    return decorator
