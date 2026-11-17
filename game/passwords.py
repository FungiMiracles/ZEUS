"""Reguła haseł kont graczy (16 Nov 2026): dłuższe niż 6 znaków (7–128), dowolne znaki — także cyfry i znaki specjalne.
Wspólna dla rejestracji (game.routes_auth) i zmiany hasła przez administratora WIKI (routes_civic_admin)."""
PASSWORD_MIN = 7
PASSWORD_MAX = 128
PASSWORD_RULE = f'Hasło musi mieć od {PASSWORD_MIN} do {PASSWORD_MAX} znaków.'


def password_error(password):
    """Komunikat błędu albo None, gdy hasło spełnia regułę."""
    if not isinstance(password, str) or not PASSWORD_MIN <= len(password) <= PASSWORD_MAX:
        return PASSWORD_RULE
    return None
