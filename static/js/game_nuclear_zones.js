/* 13 Nov 2026: strefy skażenia po uderzeniach atomowych — jaskrawozielone okręgi (promień 100 km) na każdej mapie gry.
   Skrypt rejestruje się w Leaflet (L.Map.addInitHook), więc obejmuje mapy tworzone na dowolnym ekranie. */
(()=>{
  if(!window.L||!L.Map)return;
  let request=null;
  const load=()=>request||(request=fetch('/game/strefy-skazenia',{credentials:'same-origin',cache:'no-store'}).then(r=>r.ok?r.json():{zones:[]}).catch(()=>({zones:[]})));
  const date=value=>new Intl.DateTimeFormat('pl-PL',{timeZone:'UTC',dateStyle:'short'}).format(new Date(value));
  L.Map.addInitHook(function(){
    const map=this;
    if(map.options.crs!==L.CRS.Simple)return;
    load().then(data=>{
      const zones=data.zones||[];if(!zones.length||!map.getContainer().isConnected)return;
      if(!map.getPane('nuclearZones')){map.createPane('nuclearZones');const pane=map.getPane('nuclearZones');pane.style.zIndex='430';pane.style.pointerEvents='none';}
      const unit=Number(data.kmPerUnit)||1;
      for(const zone of zones){
        L.circle([zone.y,zone.x],{pane:'nuclearZones',radius:zone.radiusKm/unit,color:'#39ff14',weight:2.5,opacity:.95,fillColor:'#39ff14',fillOpacity:.38,interactive:false,className:'nuclear-zone'}).addTo(map);
      }
      const legend=L.control({position:'bottomright'});
      legend.onAdd=()=>{const box=L.DomUtil.create('div','nuclear-zone-legend');
        box.innerHTML='<i></i><span></span>';box.querySelector('span').textContent=`Strefa skażenia atomowego (${zones.length}) — zakaz budowy do ${date(zones.map(z=>z.until).sort().pop())}`;return box;};
      legend.addTo(map);
    });
  });
  const style=document.createElement('style');
  style.textContent='.nuclear-zone-legend{display:flex;align-items:center;gap:6px;max-width:260px;padding:4px 8px;border:1px solid #1E3A5F;border-radius:6px;background:#fff;color:#1d2b40;font:600 11px/1.3 system-ui,sans-serif;box-shadow:0 2px 6px #0b1d3340}.nuclear-zone-legend i{flex:0 0 12px;width:12px;height:12px;border-radius:50%;background:#39ff14;border:2px solid #1b8f0a}';
  document.head.append(style);
})();
