(()=>{'use strict';
// Pozycja przesyłki handlowej na trasie w czasie gry. 22 Nov 2026: przesyłka z odcinkami (legs: kolej / statek / samolot)
// porusza się po bieżącym odcinku; pociąg towarowy (odcinek kolejowy) ma pomarańczową plakietkę z ikoną paczki i flagą sprzedającego.
function along(path,fraction){if(!path?.length)return null;const lengths=path.slice(1).map((p,i)=>Math.hypot(p[0]-path[i][0],p[1]-path[i][1]));let left=lengths.reduce((a,b)=>a+b,0)*Math.max(0,Math.min(1,fraction));for(let i=0;i<lengths.length;i++){const length=lengths[i];if(length&&left<=length)return path[i].map((n,k)=>n+(path[i+1][k]-n)*left/length);left-=length;}return path[path.length-1].slice();}
function leg(ship,now){const legs=ship.legs;if(!legs?.length)return null;for(const item of legs){if(now<Date.parse(item.arrivesAt))return item;}return legs[legs.length-1];}
function position(ship,now){const current=leg(ship,now);if(current&&current.path?.length>=2){const start=Date.parse(current.startsAt),end=Date.parse(current.arrivesAt);return along(current.path,(now-start)/Math.max(1,end-start));}
  const path=ship.route||[ship.source,ship.target];if(!path?.length)return null;const duration=Math.max(1,Date.parse(ship.arrivesAt)-Date.parse(ship.startsAt));return along(path,(now-Date.parse(ship.startsAt))/duration);}
function mode(ship,now){const current=leg(ship,now);return current?current.mode:(ship.transport||'sea');}
const PACKAGE_ICON='/static/icons/PACZKA.svg';
function trainSymbol(ship){const box=document.createElement('div');box.className='trade-freight-train';const icon=document.createElement('img');icon.src=PACKAGE_ICON;icon.alt='Pociąg towarowy';box.append(icon);
  const src=ship.sellerFlag||ship.flag;if(src){const flag=document.createElement('img');flag.src=src;flag.alt='Państwo sprzedające';flag.className='trade-freight-flag';flag.onerror=()=>flag.remove();box.append(flag);}return box;}
// Plakietka pociągu wymaga stylu — wstrzykiwany raz, aby działał na każdej mapie (świat, panel wojenny, handel).
if(!document.getElementById('trade-freight-style')){const style=document.createElement('style');style.id='trade-freight-style';
  style.textContent='.trade-freight-train{position:relative;box-sizing:border-box;width:28px;height:28px;padding:3px;border:2px solid #f57c00;border-radius:7px;background:#fff;box-shadow:0 0 0 2px rgba(245,124,0,.35),0 2px 5px #0006}.trade-freight-train>img:first-child{display:block;width:100%;height:100%;object-fit:contain}.trade-freight-flag{position:absolute;top:-6px;right:-9px;width:16px;height:11px;object-fit:cover;border:1px solid #fff;box-shadow:0 1px 2px #0007}';
  document.head.append(style);}
// Zmiana ikony znacznika, gdy przesyłka przechodzi na inny odcinek (kolej ↔ statek / samolot). makeIcon(mode) → L.divIcon.
function syncIcon(marker,ship,now,makeIcon){const current=mode(ship,now);if(marker._tradeMode!==current){marker._tradeMode=current;marker.setIcon(makeIcon(current));}return current;}
window.GameTradeNavigation={position,mode,leg,trainSymbol,syncIcon};})();
