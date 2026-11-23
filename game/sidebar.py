"""Stały lewy pasek gry (13 Nov 2026): flaga, wykres budżetu, wskaźniki państwa i magazyn."""
from math import cos,sin,pi

def _warehouse_keys():
    """19 Nov 2026: najpierw surowce wydobywalne, potem produkty fabryk — bez sprzętu wojskowego i amunicji."""
    from services.natural_resources import RESOURCES
    from game.industry_catalog import GOODS,ARMY_GOODS
    return [code for code,_ in RESOURCES]+[code for code in GOODS if code not in ARMY_GOODS]
WAREHOUSE_KEYS=_warehouse_keys()
# Kolory sektorów budżetu — stonowana paleta pasująca do granatu #1E3A5F.
SECTOR_COLORS={'administration':'#7fa7d9','infrastructure':'#f0b35a','armed_forces':'#d9665b','social_policy':'#9b7fd1','environment':'#5fbf8a',
               'healthcare':'#e889b5','education':'#5ec3d6','research':'#c9d35a','security_services':'#8e9bb0','propaganda':'#e07fdc','reserve':'#f2e6c9'}
FALLBACK_COLORS=['#7fa7d9','#f0b35a','#d9665b','#9b7fd1','#5fbf8a','#e889b5','#5ec3d6','#c9d35a','#8e9bb0','#e07fdc','#f2e6c9']


def warehouse_items(session,country_id):
    """Zasoby magazynu z prognozą wyczerpania (bez rozliczania produkcji — tylko odczyt)."""
    from game.commerce import goods_catalog
    from game.trade_goods import trade_warehouse
    from game.warehouse_forecast import depletion_dates
    catalog=goods_catalog();warehouse=trade_warehouse(session,country_id)
    forecasts=depletion_dates(session,country_id,warehouse)
    return [{**catalog[key],'code':key,'quantity':warehouse[key]['available'],'depletion_date':forecasts.get(key)} for key in WAREHOUSE_KEYS if key in warehouse and key in catalog]


def _point(cx,cy,r,angle):return cx+r*cos(angle),cy+r*sin(angle)


def budget_pie(items,size=180,inner=0.56):
    """Wycinki pierścienia SVG proporcjonalne do środków POZOSTAŁYCH do wydania w sektorze.

    23 Nov 2026: wcześniej wycinki odpowiadały przydziałowi, więc wykres nie zgadzał się z kwotą „Do wydania”
    w środku (suma pozostałych środków) — wyczerpany sektor wciąż zajmował dużą część koła. Udział (share) to
    teraz udział sektora w kwocie do wydania; przydział i wydatki zostają w tooltipie."""
    positive=[item for item in items if float(item.get('remaining') or 0)>0]
    total=sum(float(item['remaining']) for item in positive)
    if total<=0:return []
    cx=cy=size/2;r=size/2-2;ri=r*inner;angle=-pi/2;segments=[]
    for index,item in enumerate(positive):
        share=float(item['remaining'])/total
        if len(positive)==1:share=0.9999
        end=angle+share*2*pi;large=1 if share>0.5 else 0
        x1,y1=_point(cx,cy,r,angle);x2,y2=_point(cx,cy,r,end);x3,y3=_point(cx,cy,ri,end);x4,y4=_point(cx,cy,ri,angle)
        path=f'M{x1:.2f} {y1:.2f}A{r:.2f} {r:.2f} 0 {large} 1 {x2:.2f} {y2:.2f}L{x3:.2f} {y3:.2f}A{ri:.2f} {ri:.2f} 0 {large} 0 {x4:.2f} {y4:.2f}Z'
        segments.append({**item,'path':path,'share':round(share*100,1),
                         'color':SECTOR_COLORS.get(item.get('code'),FALLBACK_COLORS[index%len(FALLBACK_COLORS)])})
        angle=end
    return segments
