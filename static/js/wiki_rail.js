/* 20 Nov 2026: WIKI — sieć kolejowa na stronie państwa (/panstwo/<id>). Dane: game.rail.wiki_network (osadzone w stronie).
   Tory i pociągi rysuje wspólny moduł gry (static/js/game_rail_trains.js); miasta w największej spójnej sieci
   (liczonej do dochodów z kolei) mają zielony obrys. Mapa tylko do podglądu — bez budowy. */
(()=>{'use strict';
const node=document.getElementById('wiki-rail-data'),box=document.getElementById('wiki-rail-map');
if(!node||!box||!window.L)return;
const cfg=JSON.parse(node.textContent),rail=cfg.rail;
const make=(tag,text)=>{const el=document.createElement(tag);if(text!=null)el.textContent=text;return el;};
const number=v=>Number(v||0).toLocaleString('pl-PL');
const date=v=>v?new Intl.DateTimeFormat('pl-PL',{timeZone:'UTC',dateStyle:'short'}).format(new Date(v)):'—';
const coords=c=>L.latLng(c[1],c[0]);

const map=L.map(box,{crs:L.CRS.Simple,minZoom:-10,maxZoom:8,zoomSnap:.25,attributionControl:false,scrollWheelZoom:false});
map.createPane('railLines').style.zIndex='410';
map.createPane('railTrains').style.zIndex='420';map.getPane('railTrains').style.pointerEvents='none';
map.createPane('railCranes').style.zIndex='430';
map.createPane('railCities').style.zIndex='450';

// Widok przed dodaniem warstw — Leaflet nie rysuje wektorów na mapie bez ustawionego widoku.
const points=[...rail.cities.filter(c=>c.own).map(c=>coords(c.point)),...rail.lines.flatMap(l=>l.path.map(coords))];
const bounds=L.latLngBounds(points);
const fit=()=>{if(bounds.isValid()&&map.getSize().x&&map.getSize().y)map.fitBounds(bounds.pad(.15),{maxZoom:4,animate:false});};
if(bounds.isValid())map.setView(bounds.getCenter(),0,{animate:false});
fit();

function tip(line){
  const el=make('div');el.append(make('strong',`${line.cityAName} – ${line.cityBName}`));
  el.append(make('div',`${number(Math.round(Number(line.distanceKm)))} km · ${line.initiator}${line.partner?' + '+line.partner:''}`));
  el.append(make('div',line.completed?'Linia ukończona':`Budowa: ${line.progress}% · ukończenie ${date(line.readyAt)}`));
  return el;
}

const tracks=window.GameRailTrains;
for(const line of rail.lines){
  const latlngs=line.path.map(p=>[p[1],p[0]]);
  if(tracks)tracks.track(line.path,{pane:'railLines',color:line.completed?'#26313f':'#7a8597',faded:!line.completed,dashed:!line.completed}).addTo(map);
  else L.polyline(latlngs,{pane:'railLines',color:'#26313f',weight:2,dashArray:line.completed?null:'6 5'}).addTo(map);
  L.polyline(latlngs,{pane:'railLines',color:'#000',weight:14,opacity:0}).bindTooltip(tip(line),{sticky:true}).addTo(map);
  if(!line.completed){
    const crane=make('div');crane.className='wiki-rail-crane';const img=make('img');img.src=cfg.craneIcon;img.alt='';crane.append(img);
    L.marker(latlngs[Math.floor(latlngs.length/2)],{pane:'railCranes',keyboard:false,
      icon:L.divIcon({html:crane,className:'wiki-rail-crane-marker',iconSize:[20,20],iconAnchor:[10,10]})}).bindTooltip(tip(line),{direction:'top',offset:[0,-10]}).addTo(map);
  }
}

for(const city of rail.cities){
  const marker=L.circleMarker(coords(city.point),{pane:'railCities',radius:city.own?5:4,color:city.inNetwork?'#1f8a3b':'#22301f',
    weight:city.inNetwork?2.6:1.6,fillColor:city.own?'#ffffff':'#c9ced6',fillOpacity:1});
  const el=make('div');el.append(make('strong',city.name),make('div',`${rail.countries[String(city.countryId)]||''} · ${number(city.population)} mieszk.`));
  if(city.inNetwork)el.append(make('div','W spójnej sieci kolejowej'));
  marker.bindTooltip(el,{direction:'top',offset:[0,-6]}).addTo(map);
}

const done=rail.lines.filter(l=>l.completed);
if(tracks&&done.length)tracks.trains(map,done,{pane:'railTrains',gameNow:rail.gameNow,timeMultiplier:rail.timeMultiplier,speed:rail.trainSpeed});

if(window.ResizeObserver){let first=true;new ResizeObserver(()=>{map.invalidateSize();if(first){first=false;fit();}}).observe(box);}

fetch(cfg.countriesUrl,{credentials:'same-origin'}).then(r=>r.ok?r.json():null).then(countries=>{
  if(!countries)return;
  const own=Number(rail.countryId);
  L.geoJSON(countries,{coordsToLatLng:coords,interactive:false,style:f=>{const id=Number(f.properties?.panstwo_id);
    return {color:'#667C63',weight:1,fillOpacity:1,fillColor:id===own?'#B8C9B0':rail.countries[String(id)]?'#DCE3D4':'#F1F2EE'};}}).addTo(map).bringToBack();
}).catch(()=>{});
})();
