"""Shared financial presentation; storage and calculations remain exact ROI."""
from decimal import Decimal,InvalidOperation,localcontext,ROUND_HALF_UP


def format_money(value,currency=True):
    try:
        amount=Decimal(str(value))
        if not amount.is_finite():return '—'
        absolute=abs(amount)
        divisor,unit=(Decimal('1e12'),'BLN') if absolute>Decimal('1e12') else (Decimal('1e9'),'MLD') if absolute>Decimal('1e9') else (Decimal('1e6'),'MLN')
        with localcontext() as context:
            context.prec=64;rounded=(amount/divisor).quantize(Decimal('.1'),rounding=ROUND_HALF_UP)
        if rounded==0:rounded=abs(rounded)
        text=format(rounded,',.1f').replace(',','\u00a0').replace('.',',')
        return f'{text} {unit}'+(' ROI' if currency else '')
    except (ValueError,TypeError,InvalidOperation):return '—'
