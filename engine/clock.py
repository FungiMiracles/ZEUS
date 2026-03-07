from datetime import datetime
import os

# =====================================================
# WSPÓŁCZYNNIK CZASU
# 1 dzień Entendy = 2 godziny realne
# =====================================================

TIME_MULTIPLIER = 2500

# =====================================================
# PUNKT STARTOWY CZASU ENTENDY
# =====================================================

ENTENDA_START = datetime(2990, 1, 1)

# moment startu symulacji w czasie rzeczywistym
REAL_START = datetime(2025, 11, 28)

# =====================================================
# AKTUALNA DATA ENTENDY
# =====================================================

def get_current_entenda_date():

    now_real = datetime.utcnow()

    real_delta = now_real - REAL_START

    entenda_delta = real_delta * TIME_MULTIPLIER

    return ENTENDA_START + entenda_delta


# =====================================================
# POMOCNICZE FUNKCJE
# =====================================================

def get_entenda_year():
    return get_current_entenda_date().year


def get_entenda_month():
    return get_current_entenda_date().month


def get_entenda_day():
    return get_current_entenda_date().day