(()=>{'use strict';
// Pozycja przesyłki handlowej na trasie w czasie gry. 22 Nov 2026: przesyłka z odcinkami (legs: kolej / statek / samolot)
// porusza się po bieżącym odcinku; pociąg towarowy (odcinek kolejowy) ma pomarańczową plakietkę z ikoną paczki i flagą sprzedającego.
function along(path,fraction){if(!path?.length)return null;const lengths=path.slice(1).map((p,i)=>Math.hypot(p[0]-path[i][0],p[1]-path[i][1]));let left=lengths.reduce((a,b)=>a+b,0)*Math.max(0,Math.min(1,fraction));for(let i=0;i<lengths.length;i++){const length=lengths[i];if(length&&left<=length)return path[i].map((n,k)=>n+(path[i+1][k]-n)*left/length);left-=length;}return path[path.length-1].slice();}
function leg(ship,now){const legs=ship.legs;if(!legs?.length)return null;for(const item of legs){if(now<Date.parse(item.arrivesAt))return item;}return legs[legs.length-1];}
function position(ship,now){const current=leg(ship,now);if(current&&current.path?.length>=2){const start=Date.parse(current.startsAt),end=Date.parse(current.arrivesAt);return along(current.path,(now-start)/Math.max(1,end-start));}
  const path=ship.route||[ship.source,ship.target];if(!path?.length)return null;const duration=Math.max(1,Date.parse(ship.arrivesAt)-Date.parse(ship.startsAt));return along(path,(now-Date.parse(ship.startsAt))/duration);}
function mode(ship,now){const current=leg(ship,now);return current?current.mode:(ship.transport||'sea');}
const PACKAGE_ICON='/static/icons/PACZKA.svg';
// 23 Nov 2026: pociąg towarowy wygląda jak pociąg na mapach (czerwony prostokąt 11 × 5 px, obrócony w kierunku jazdy),
// a obok — plakietka z ikoną paczki (i flagą sprzedającego) z „dzióbkiem” wskazującym jadący pociąg. Plakietka 28 × 28,
// punkt zaczepienia = środek pociągu. 25 Nov 2026: ikona paczki (36 px) i flaga (26 × 18 px) dwukrotnie większe.
function trainSymbol(ship){const box=document.createElement('div');box.className='trade-freight-train';
  const train=document.createElement('span');train.className='trade-freight-loco rail-train';box.append(train);
  const bubble=document.createElement('span');bubble.className='trade-freight-parcel';const icon=document.createElement('img');icon.src=PACKAGE_ICON;icon.alt='Pociąg towarowy';bubble.append(icon);box.append(bubble);
  const src=ship.sellerFlag||ship.flag;if(src){const flag=document.createElement('img');flag.src=src;flag.alt='Państwo sprzedające';flag.className='trade-freight-flag';flag.onerror=()=>flag.remove();bubble.append(flag);}return box;}
// Plakietka pociągu wymaga stylu — wstrzykiwany raz, aby działał na każdej mapie (świat, panel wojenny, handel).
if(!document.getElementById('trade-freight-style')){const style=document.createElement('style');style.id='trade-freight-style';
  style.textContent='.trade-freight-train{position:relative;width:28px;height:28px;pointer-events:auto}'
    +'.trade-freight-loco{position:absolute;left:8.5px;top:11.5px;width:11px;height:5px;box-sizing:border-box;border:1px solid #fff;border-radius:1.5px;background:#b3261e;box-shadow:0 0 1.5px #0009;transform-origin:50% 50%}'
    +'.trade-freight-parcel{position:absolute;left:17px;top:-27px;box-sizing:border-box;width:36px;height:36px;padding:4px;border:2px solid #f57c00;border-radius:6px;background:#fff;box-shadow:0 1px 3px #0006}'
    +'.trade-freight-parcel::after{content:"";position:absolute;left:-2px;bottom:-9px;border-style:solid;border-width:9px 9px 0 0;border-color:#f57c00 transparent transparent transparent;transform:skewX(-20deg)}'
    +'.trade-freight-parcel>img:first-child{display:block;width:100%;height:100%;object-fit:contain}'
    +'.trade-freight-flag{position:absolute;top:-10px;right:-16px;width:26px;height:18px;object-fit:cover;border:1px solid #fff;box-shadow:0 1px 2px #0007}';
  document.head.append(style);}
// Obrót pociągu w kierunku jazdy (kierunek z pozycji teraz i chwilę później w czasie gry).
function orient(marker,ship,now){const loco=marker.getElement?.()?.querySelector('.trade-freight-loco');if(!loco)return;
  const a=position(ship,now),b=position(ship,now+60000);if(!a||!b||(a[0]===b[0]&&a[1]===b[1]))return;
  loco.style.transform=`rotate(${Math.atan2(-(b[1]-a[1]),b[0]-a[0])*180/Math.PI}deg)`;}
// Zmiana ikony znacznika, gdy przesyłka przechodzi na inny odcinek (kolej ↔ statek / samolot). makeIcon(mode) → L.divIcon.
function syncIcon(marker,ship,now,makeIcon){const current=mode(ship,now);if(marker._tradeMode!==current){marker._tradeMode=current;marker.setIcon(makeIcon(current));}if(current==='land')orient(marker,ship,now);return current;}
window.GameTradeNavigation={position,mode,leg,trainSymbol,syncIcon,orient};})();
