/* 19 Nov 2026: kolej — wspólne rysowanie torów i animacja pociągów (zakładka „Komunikacja” i mapa świata).
   Pociąg to mały prostokąt jadący po ukończonej linii tam i z powrotem z prędkością 120 km/h czasu gry
   (zegar gry: gameNow + upływ czasu rzeczywistego × mnożnik czasu). Linie międzynarodowe — tak samo.
   19 Nov 2026: pociąg 22 × 10 px (dwukrotnie powiększony). Liczba pociągów na linii: 1 na każde rozpoczęte 400 km (najwyżej 3), równo rozstawione. */
(()=>{'use strict';
if(!window.L)return;
const make=(tag,cls)=>{const el=document.createElement(tag);if(cls)el.className=cls;return el;};

function style(){
  if(document.getElementById('rail-trains-style'))return;
  const css=make('style');css.id='rail-trains-style';
  css.textContent='.rail-train-marker{background:transparent;border:0}.rail-train{width:22px;height:10px;box-sizing:border-box;border:1.5px solid #fff;border-radius:3px;background:#b3261e;box-shadow:0 0 2px #0009;transform-origin:50% 50%}';
  document.head.append(css);
}

/** Tor: cienka linia i poprzeczne kreski (podkłady). options: pane, color, faded, dashed. */
function track(path,options={}){
  const latlngs=path.map(p=>[p[1],p[0]]),group=L.layerGroup(),color=options.color||'#26313f',faded=!!options.faded;
  L.polyline(latlngs,{pane:options.pane,color,weight:2,opacity:faded?.75:1,dashArray:options.dashed?'6 5':null,interactive:false}).addTo(group);
  L.polyline(latlngs,{pane:options.pane,color,weight:7,opacity:faded?.55:.95,dashArray:'1.5 9',lineCap:'butt',interactive:false}).addTo(group);
  return group;
}

function measure(path){
  const lengths=[0];for(let i=1;i<path.length;i++)lengths.push(lengths[i-1]+Math.hypot(path[i][0]-path[i-1][0],path[i][1]-path[i-1][1]));
  return lengths;
}

function pointAt(path,lengths,distance){
  const total=lengths[lengths.length-1];distance=Math.max(0,Math.min(total,distance));
  let i=1;while(i<lengths.length-1&&lengths[i]<distance)i++;
  const a=path[i-1],b=path[i],span=(lengths[i]-lengths[i-1])||1,t=(distance-lengths[i-1])/span;
  return {x:a[0]+(b[0]-a[0])*t,y:a[1]+(b[1]-a[1])*t,angle:Math.atan2(-(b[1]-a[1]),b[0]-a[0])*180/Math.PI};
}

/** Pociągi na ukończonych liniach. lines: [{path, distanceKm, completed}], options: gameNow, timeMultiplier, speed, pane, layer. */
function trains(map,lines,options){
  style();
  const layer=options.layer||L.layerGroup().addTo(map);
  const anchor=Date.parse(options.gameNow),start=performance.now(),multiplier=Number(options.timeMultiplier)||1,speed=Number(options.speed)||120;
  const gameHours=()=>(anchor+(performance.now()-start)*multiplier)/3600000;
  const items=[];
  for(const line of lines||[]){
    if(!line.completed||!line.path||line.path.length<2)continue;
    const km=Number(line.distanceKm)||0;if(km<=0)continue;
    const lengths=measure(line.path),count=Math.min(3,Math.max(1,Math.ceil(km/400)));
    for(let k=0;k<count;k++){
      const box=make('div','rail-train');
      const marker=L.marker([line.path[0][1],line.path[0][0]],{pane:options.pane,interactive:false,keyboard:false,
        icon:L.divIcon({html:box,className:'rail-train-marker',iconSize:[22,10],iconAnchor:[11,5]})}).addTo(layer);
      items.push({line,lengths,km,offset:k*2*km/count,marker,box});
    }
  }
  function tick(){
    if(document.hidden||!items.length)return;
    const travelled=gameHours()*speed;
    for(const item of items){
      let d=(travelled+item.offset)%(2*item.km);const back=d>item.km;if(back)d=2*item.km-d;
      const total=item.lengths[item.lengths.length-1],p=pointAt(item.line.path,item.lengths,d/item.km*total);
      item.marker.setLatLng([p.y,p.x]);item.box.style.transform=`rotate(${back?p.angle+180:p.angle}deg)`;
    }
  }
  tick();const timer=items.length?setInterval(tick,120):null;
  return {stop(){if(timer)clearInterval(timer);for(const item of items)item.marker.remove();},count:items.length};
}

window.GameRailTrains={track,trains};
})();
