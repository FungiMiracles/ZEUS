/* 20 Nov 2026: transport lotniczy — samoloty lecące między portami lotniczymi (mapa „Świat”).
   Na każdym czynnym połączeniu lata jeden samolot tam i z powrotem (prędkość z serwera, km/h czasu gry; zegar gry:
   gameNow + upływ czasu rzeczywistego × mnożnik czasu). Samolot jest obrócony dziobem w kierunku lotu, bez rysowania
   trajektorii; tooltip pokazuje lotnisko docelowe. Ikona SAMOLOT.svg ma dziób skierowany w prawo-górę (−45°). */
(()=>{'use strict';
if(!window.L)return;
const make=(tag,cls,text)=>{const el=document.createElement(tag);if(cls)el.className=cls;if(text!=null)el.textContent=text;return el;};
const ICON_HEADING=-45;   // kierunek dzioba w ikonie (stopnie, ekran: 0 = w prawo, dodatnie zgodnie z ruchem wskazówek zegara)

/** air: {airports:[{id,name,cityName,country,position}], routes:[{a,b,distanceKm}]}; options: pane, layer, gameNow, timeMultiplier, speed, icon. */
function planes(map,air,options){
  const layer=options.layer||L.layerGroup().addTo(map);
  const airports=new Map((air.airports||[]).map(a=>[a.id,a]));
  const anchor=Date.parse(options.gameNow),start=performance.now(),multiplier=Number(options.timeMultiplier)||1,speed=Number(options.speed)||1000;
  const gameHours=()=>(anchor+(performance.now()-start)*multiplier)/3600000;
  const items=[];
  for(const route of air.routes||[]){
    const a=airports.get(route.a),b=airports.get(route.b),km=Number(route.distanceKm)||0;
    if(!a||!b||km<=0)continue;
    // 23 Nov 2026: powrót do pierwotnego wyglądu — czarna ikona SAMOLOT.svg bez poświaty (było: pomarańczowa maska z 21 Nov 2026)
    const box=make('div','world-plane'),img=make('img');img.src=options.icon;img.alt='';box.append(img);
    const tip=make('div','world-tip'),text=make('div'),title=make('strong'),line=make('div');text.append(title,line);tip.append(text);
    const marker=L.marker([a.position[1],a.position[0]],{pane:options.pane,keyboard:false,
      icon:L.divIcon({html:box,className:'world-plane-marker',iconSize:[22,22],iconAnchor:[11,11]})})
      .bindTooltip(tip,{direction:'top',offset:L.point(0,-10),className:'world-tooltip'}).addTo(layer);
    const offset=((route.a*7919+route.b*104729)%997)/997*2*km;   // rozłożenie samolotów na trasach
    items.push({a,b,km,offset,marker,box,title,line,heading:null});
  }
  function tick(){
    if(document.hidden||!items.length)return;
    const travelled=gameHours()*speed;
    for(const item of items){
      let d=(travelled+item.offset)%(2*item.km);const back=d>item.km;if(back)d=2*item.km-d;
      const from=back?item.b:item.a,to=back?item.a:item.b,t=d/item.km;
      const x=item.a.position[0]+(item.b.position[0]-item.a.position[0])*t,y=item.a.position[1]+(item.b.position[1]-item.a.position[1])*t;
      item.marker.setLatLng([y,x]);
      const angle=Math.atan2(-(to.position[1]-from.position[1]),to.position[0]-from.position[0])*180/Math.PI;
      item.box.style.transform=`rotate(${angle-ICON_HEADING}deg)`;
      if(item.heading!==to.id){
        item.heading=to.id;
        item.title.textContent=`Lot do: ${to.name}`;
        item.line.textContent=`${from.cityName} (${from.country}) → ${to.cityName} (${to.country}) · ${Math.round(item.km).toLocaleString('pl-PL')} km`;
      }
    }
  }
  tick();const timer=items.length?setInterval(tick,150):null;
  return {stop(){if(timer)clearInterval(timer);for(const item of items)item.marker.remove();},count:items.length};
}

window.GameAirTraffic={planes};
})();
