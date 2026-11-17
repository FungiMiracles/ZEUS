(() => {
'use strict';
// 13 Nov 2026: ekran „Świat” — mapa polityczna / regionalna w kolorystyce mapy panelu państwa.
const node = document.getElementById('world-config'); if (!node) return;
const config = JSON.parse(node.textContent);
const status = document.getElementById('world-map-status');
const say = text => { status.textContent = text; status.hidden = false; };
if (!window.L) { say('Nie udało się załadować biblioteki mapy.'); return; }
const C = { land: '#B8C9B0', own: '#a6bd9c', border: '#667C63', hover: '#D5E5C6', regionBorder: '#7d9178', occupied: '#d98b7a', city: '#FFFFFF', cityBorder: '#22301f', capital: '#D99A26' };
const make = (tag, text, cls) => { const el = document.createElement(tag); if (text != null) el.textContent = text; if (cls) el.className = cls; return el; };
const mln = value => value == null ? 'brak danych' : (Number(value) / 1e6).toLocaleString('pl-PL', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' mln';
const coordinates = c => L.latLng(c[1], c[0]);
const load = url => fetch(url, { credentials: 'same-origin' }).then(r => { if (!r.ok) throw new Error(r.status); return r.json(); });
const map = L.map('world-map', { crs: L.CRS.Simple, minZoom: -10, maxZoom: 8, zoomSnap: 0.25, zoomDelta: 0.5, attributionControl: false });
for (const [name, z] of [['worldGrid', 380], ['worldRegions', 400], ['worldCountries', 410], ['worldBorders', 420], ['worldCities', 600]]) { map.createPane(name); map.getPane(name).style.zIndex = String(z); }
map.getPane('worldGrid').style.pointerEvents = 'none'; map.getPane('worldBorders').style.pointerEvents = 'none';
const tipOptions = { sticky: true, direction: 'auto', offset: L.point(16, 0), className: 'world-tooltip' };
function iconTip(src, title, lines, round = false) {
  const box = make('div', null, 'world-tip'); const img = make('img', null, round ? 'is-flag' : ''); img.src = src; img.alt = '';
  const text = make('div'); text.append(make('strong', title)); for (const line of lines) text.append(make('div', line)); box.append(img, text); return box;
}
function countryTip(id) {
  const c = config.countries[String(id)]; if (!c) return null;
  return iconTip(c.flag, c.fullName || c.name, [`Ustrój: ${c.regime || 'brak danych'}`, `Populacja: ${mln(c.population)}`, `PKB: ${c.gdp || 'brak danych'}`], true);
}
Promise.all([load(config.countriesUrl), load(config.regionsUrl)]).then(([countries, regions]) => {
  // --- widok polityczny: państwa ---
  const countryStyle = feature => ({ color: C.border, weight: 1.6, fillColor: Number(feature.properties?.panstwo_id) === config.countryId ? C.own : C.land, fillOpacity: 1 });
  const political = L.geoJSON(countries, { pane: 'worldCountries', coordsToLatLng: coordinates, style: countryStyle,
    onEachFeature: (feature, layer) => {
      const tip = countryTip(feature.properties?.panstwo_id); if (tip) layer.bindTooltip(tip, tipOptions);
      layer.on('mouseover', () => layer.setStyle({ fillColor: C.hover })); layer.on('mouseout', () => political.resetStyle(layer));
    } });
  // --- widok regionalny: regiony (cienkie granice) + granice państw (grubsze) + okupacje ---
  const regionStyle = feature => {
    const id = String(feature.properties?.region_id), occupied = config.occupied[id];
    return { color: C.regionBorder, weight: .6, fillColor: occupied ? C.occupied : C.land, fillOpacity: 1 };
  };
  const regional = L.layerGroup();
  function regionTip(id) {
    const r=config.regions[id],occupied=config.occupied[id],owner=config.countries[String(r.countryId)];
    const lines=[`Populacja: ${mln(r.population)}`];
    if(owner)lines.push(`Państwo: ${owner.name}`);
    if(occupied)lines.push(`Okupowany przez: ${occupied.occupier || 'nieznane państwo'}`);
    return iconTip(owner ? owner.flag : config.regionIcon,r.name,lines,!!owner);
  }
  const regionLayer = L.geoJSON(regions, { pane: 'worldRegions', coordsToLatLng: coordinates, style: regionStyle, filter: f => !!config.regions[String(f.properties?.region_id)],
    onEachFeature: (feature, layer) => {
      const id = String(feature.properties.region_id);
      layer.bindTooltip(regionTip(id), tipOptions);
      layer.on('mouseover', () => layer.setStyle({ fillColor: C.hover })); layer.on('mouseout', () => regionLayer.resetStyle(layer));
    } }).addTo(regional);
  L.geoJSON(countries, { pane: 'worldBorders', coordsToLatLng: coordinates, interactive: false, style: { color: C.border, weight: 2, fill: false } }).addTo(regional);
  // --- widok kontynentów: państwa w kolorze kontynentu, granice państw ledwie widoczne ---
  const CONTINENT_COLORS = ['#B8C9B0', '#c9b98f', '#a9bcc9', '#c7a9a2', '#b3a9c9', '#a9c9b8', '#c9c2a9'];
  const continentIds = Object.keys(config.continents || {}).sort();
  const continentColor = id => CONTINENT_COLORS[Math.max(0, continentIds.indexOf(String(id))) % CONTINENT_COLORS.length];
  const continentOf = feature => (config.countries[String(feature.properties?.panstwo_id)] || {}).continentId;
  const continentStyle = feature => ({ color: continentColor(continentOf(feature)), weight: 1, fillColor: continentColor(continentOf(feature)), fillOpacity: 1 });
  const continentLayer = L.geoJSON(countries, { pane: 'worldCountries', coordsToLatLng: coordinates, style: continentStyle,
    onEachFeature: (feature, layer) => {
      const id = continentOf(feature), c = (config.continents || {})[id]; if (!c) return;
      const tip = make('div', null, 'world-tip'); const text = make('div');
      text.append(make('strong', c.name), make('div', `Populacja: ${mln(c.population)}`), make('div', `Liczba państw: ${c.countries}`), make('div', `Łączne PKB: ${c.gdp}`)); tip.append(text);
      layer.bindTooltip(tip, tipOptions);
      layer.on('mouseover', () => continentLayer.eachLayer(other => { if (continentOf(other.feature) === id) other.setStyle({ fillColor: C.hover, color: C.hover }); }));
      layer.on('mouseout', () => continentLayer.eachLayer(other => { if (continentOf(other.feature) === id) continentLayer.resetStyle(other); }));
    } });
  // --- siatka równoleżników i południków ---
  const bounds = political.getBounds().isValid() ? political.getBounds() : regionLayer.getBounds();
  if (bounds.isValid()) {
    const pad = 0.15, south = bounds.getSouth(), north = bounds.getNorth(), west = bounds.getWest(), east = bounds.getEast();
    const h = north - south, w = east - west, s0 = south - h * pad, n0 = north + h * pad, w0 = west - w * pad, e0 = east + w * pad;
    const step = Math.max(h, w) / 14, grid = { pane: 'worldGrid', color: '#ffffff', weight: .6, opacity: .16, interactive: false, dashArray: '3 5' };
    for (let y = Math.floor(s0 / step) * step; y <= n0; y += step) L.polyline([[y, w0], [y, e0]], grid).addTo(map);
    for (let x = Math.floor(w0 / step) * step; x <= e0; x += step) L.polyline([[s0, x], [n0, x]], grid).addTo(map);
  }
  // --- przełącznik widoku ---
  const views = { political, regional, continents: continentLayer };
  function setView(view) { if (!views[view]) view = 'political'; for (const [name, layer] of Object.entries(views)) { if (name === view) layer.addTo(map); else layer.remove(); }
    document.querySelector('.legend-regional').hidden = view !== 'regional'; map.fire('worldviewchange', {view}); try { localStorage.setItem('world-view', view); } catch {} }
  let saved = 'political'; try { saved = localStorage.getItem('world-view') || 'political'; } catch {}
  for (const radio of document.querySelectorAll('[name="world-view"]')) { radio.checked = radio.value === saved; radio.addEventListener('change', () => setView(radio.value)); }
  setView(saved);
  // Cieniowana rzeźba terenu w geometrii regionów, pod miastami i granicami.
  const reliefToggle = document.getElementById('world-relief-toggle');
  if (window.WorldRelief && reliefToggle) {
    map.createPane('worldRelief'); map.getPane('worldRelief').style.zIndex = '415'; map.getPane('worldRelief').style.pointerEvents = 'none';
    const relief = window.WorldRelief.createLayer(L, regions, config.regions);
    // Transparent hit areas above the opaque terrain tiles. All pieces of a
    // region share one 50%-opaque highlight, without changing the base map.
    map.createPane('worldRegionHover');map.getPane('worldRegionHover').style.zIndex='430';
    const hoverGroups=new Map();let hoveredRegion=null;
    const hoverStyle={color:'#29486b',weight:1.2,opacity:0,fill:true,fillColor:C.hover,fillOpacity:0};
    function clearRegionHover() {
      for(const layer of hoverGroups.get(hoveredRegion)||[])layer.setStyle(hoverStyle);
      hoveredRegion=null;
    }
    const regionHover=L.geoJSON(regions,{pane:'worldRegionHover',coordsToLatLng:coordinates,
      filter:feature=>!!config.regions[String(feature.properties?.region_id)],style:hoverStyle,
      onEachFeature:(feature,layer)=>{
        const id=String(feature.properties.region_id);
        if(!hoverGroups.has(id))hoverGroups.set(id,[]);hoverGroups.get(id).push(layer);
        layer.bindTooltip(regionTip(id),tipOptions);
        layer.on('mouseover',()=>{
          clearRegionHover();hoveredRegion=id;
          for(const part of hoverGroups.get(id))part.setStyle({opacity:.8,fillOpacity:.5});
        });
        layer.on('mouseout',clearRegionHover);
      }});
    map.on('movestart worldviewchange',clearRegionHover);
    relief.setOpacity(saved === 'continents' ? .4 : 1);
    map.on('worldviewchange', event => relief.setOpacity(event.view === 'continents' ? .4 : 1));
    map.createPane('worldShelf'); map.getPane('worldShelf').style.zIndex='390'; map.getPane('worldShelf').style.pointerEvents='none';
    const shelf=L.geoJSON(countries,{pane:'worldShelf',coordsToLatLng:coordinates,interactive:false,
      style:{color:'#daedf3',weight:7,opacity:1,fill:false}});
    const reliefBorders = L.geoJSON(countries, {pane:'worldBorders', coordsToLatLng:coordinates, interactive:false,
      style:{color:'#7e8975',weight:1,fill:false,opacity:.7}});
    const reliefRegions = L.geoJSON(regions, {pane:'worldBorders', coordsToLatLng:coordinates, interactive:false,
      style:feature => {
        const occupied = !!config.occupied[String(feature.properties?.region_id)];
        return {color:occupied ? C.occupied : C.regionBorder,weight:occupied ? 1.8 : .55,opacity:occupied ? 1 : .5,
          fill:occupied,fillColor:C.occupied,fillOpacity:.22};
      }});
    function setRelief(on) {
      map.getContainer().classList.toggle('world-map-physical',on);
      document.querySelectorAll('.legend-terrain').forEach(item=>{item.hidden=!on;});
      clearRegionHover();
      if (on) { shelf.addTo(map); relief.addTo(map); reliefBorders.addTo(map); reliefRegions.addTo(regional); regionHover.addTo(map); }
      else { regionHover.remove(); shelf.remove(); relief.remove(); reliefBorders.remove(); regional.removeLayer(reliefRegions); }
      try { localStorage.setItem('world-relief', on ? '1' : '0'); } catch {}
    }
    let showRelief = true; try { showRelief = localStorage.getItem('world-relief') !== '0'; } catch {}
    reliefToggle.checked = showRelief;
    reliefToggle.addEventListener('change', () => setRelief(reliefToggle.checked)); setRelief(showRelief);
  }
  const fit = () => { map.invalidateSize(); if (bounds.isValid()) map.fitBounds(bounds, { padding: [20, 20], animate: false }); };
  fit(); document.getElementById('world-map-reset').addEventListener('click', fit);
  // --- wody terytorialne (15 Nov 2026): filtr widoczny we wszystkich widokach, wczytywany przy pierwszym włączeniu ---
  map.createPane('worldWaters'); map.getPane('worldWaters').style.zIndex = '395';
  const watersToggle = document.getElementById('world-waters-toggle'), watersLegend = document.querySelector('.legend-waters');
  let watersLayer = null, watersLoading = null;
  const watersStyle = feature => {
    const own = Number(feature.properties?.panstwo_id) === config.countryId;
    return { color: own ? '#ffcf6b' : '#9fd8ff', weight: own ? 1.2 : .9, opacity: own ? .95 : .75, fillColor: own ? '#ffcf6b' : '#8fd3ff', fillOpacity: own ? .32 : .24 };
  };
  function loadWaters() {
    if (!watersLoading) watersLoading = load(config.watersUrl).then(data => {
      watersLayer = L.geoJSON(data, { pane: 'worldWaters', coordsToLatLng: coordinates, style: watersStyle,
        onEachFeature: (feature, layer) => {
          const c = config.countries[String(feature.properties?.panstwo_id)];
          const lines = ['Wody terytorialne: 100 km od wybrzeża']; if (Number(feature.properties?.panstwo_id) === config.countryId) lines.push('Twoje państwo');
          layer.bindTooltip(c ? iconTip(c.flag, c.name, lines, true) : make('span', 'Wody terytorialne'), tipOptions);
          layer.on('mouseover', () => layer.setStyle({ fillOpacity: .45 })); layer.on('mouseout', () => watersLayer.resetStyle(layer));
        } });
      return watersLayer;
    }).catch(error => { watersLoading = null; throw error; });
    return watersLoading;
  }
  function setWaters(on) {
    if (watersLegend) watersLegend.hidden = !on;
    try { localStorage.setItem('world-waters', on ? '1' : '0'); } catch {}
    if (!on) { if (watersLayer) watersLayer.remove(); return; }
    loadWaters().then(layer => { if (watersToggle.checked) layer.addTo(map); })
      .catch(() => { watersToggle.checked = false; if (watersLegend) watersLegend.hidden = true; say('Nie udało się wczytać wód terytorialnych.'); });
  }
  if (watersToggle && config.watersUrl) {
    let showWaters = false; try { showWaters = localStorage.getItem('world-waters') === '1'; } catch {}
    watersToggle.checked = showWaters; watersToggle.addEventListener('change', () => setWaters(watersToggle.checked));
    if (showWaters) setWaters(true);
  }
  // --- miasta (16 Nov 2026: przełącznik pokaż/ukryj, zapamiętywany w przeglądarce) ---
  const citiesToggle = document.getElementById('world-cities-toggle'), citiesLegend = document.querySelectorAll('.legend-cities');
  let citiesLayer = null;
  const setCities = on => {
    citiesLegend.forEach(item => { item.hidden = !on; });
    try { localStorage.setItem('world-cities', on ? '1' : '0'); } catch {}
    if (citiesLayer) { if (on) citiesLayer.addTo(map); else citiesLayer.remove(); }
  };
  if (citiesToggle) {
    let showCities = true; try { showCities = localStorage.getItem('world-cities') !== '0'; } catch {}
    citiesToggle.checked = showCities; citiesLegend.forEach(item => { item.hidden = !showCities; });
    citiesToggle.addEventListener('change', () => setCities(citiesToggle.checked));
  }
  load(config.citiesUrl).then(cities => {
    citiesLayer = window.WorldCityMarkers.createLayer(L,map,cities,config.cities,{
      land:regions,
      tooltip:city=>iconTip(config.cityIcon,city.name,[`Populacja: ${mln(city.population)}`,`Rodzaj: ${city.type || 'brak danych'}`,`Portowe: ${city.port ? 'tak' : 'nie'}`])
    });
    if (!citiesToggle || citiesToggle.checked) citiesLayer.addTo(map);
  }).catch(() => say('Mapa została wczytana, ale nie udało się wyświetlić miast.'));
  // --- płynące statki towarowe ---
  map.createPane('worldShips'); map.getPane('worldShips').style.zIndex = '640';
  const anchor = Date.parse(config.gameNow), realAnchor = performance.now(), gameTime = () => anchor + (performance.now() - realAnchor) * (config.timeMultiplier || 1);
  const ships = [];
  for (const ship of config.ships || []) {
    L.polyline((ship.route || [ship.source, ship.target]).map(p => [p[1], p[0]]), { pane: 'worldShips', color: '#ffffff', weight: 1, opacity: .35, dashArray: '4 6', interactive: false }).addTo(map);
    const symbol = make('div', null, 'world-ship'); const img = make('img'); img.src = config.shipIcon; img.alt = ''; symbol.append(img);
    if (ship.flag) { const flag = make('img', null, 'world-ship-flag'); flag.src = ship.flag; flag.alt = ''; symbol.append(flag); }
    const point = window.GameTradeNavigation?.position(ship, gameTime()); if (!point) continue;
    const marker = L.marker([point[1], point[0]], { pane: 'worldShips', icon: L.divIcon({ html: symbol, className: 'world-ship-marker', iconSize: [26, 26], iconAnchor: [13, 13] }) })
      .bindTooltip(iconTip(config.shipIcon, 'Statek towarowy', [`${ship.seller || '?'} → ${ship.buyer || '?'}`, `Przypłynie: ${new Intl.DateTimeFormat('pl-PL', { timeZone: 'UTC', dateStyle: 'short', timeStyle: 'short' }).format(new Date(ship.arrivesAt))}`]), { direction: 'top', className: 'world-tooltip' }).addTo(map);
    ships.push([ship, marker]);
  }
  if (ships.length && window.GameTradeNavigation) setInterval(() => { const now = gameTime(); for (const [ship, marker] of ships) { if (now >= Date.parse(ship.arrivesAt)) { marker.remove(); continue; } const p = window.GameTradeNavigation.position(ship, now); if (p) marker.setLatLng([p[1], p[0]]); } }, 1000);
  // --- okręty wojenne i lotniskowce wszystkich państw (14 Nov 2026) ---
  const kinds = { warships: 'Okręt wojenny', carriers: 'Lotniskowiec', submarines: 'Okręt podwodny' };
  const statuses = { sailing: 'w rejsie', returning: 'powrót do bazy', stationed: 'na pozycji' };
  const vessels = [];
  for (const vessel of config.vessels || []) {
    const icon = (config.vesselIcons || {})[vessel.kind]; if (!icon) continue;
    // 14 Nov 2026: trasa okrętu widoczna dopiero po najechaniu na okręt
    const route = vessel.status !== 'stationed' && vessel.route && vessel.route.length > 1 ? L.polyline(vessel.route.map(p => [p[1], p[0]]), { pane: 'worldShips', color: '#ffffff', weight: 1.5, opacity: .7, dashArray: '5 5', interactive: false }) : null;
    const symbol = make('div', null, 'world-ship world-vessel'); const img = make('img'); img.src = icon; img.alt = ''; symbol.append(img);
    if (vessel.flag) { const flag = make('img', null, 'world-ship-flag'); flag.src = vessel.flag; flag.alt = ''; symbol.append(flag); }
    const point = window.GameTradeNavigation?.position(vessel, gameTime()); if (!point) continue;
    const label = vessel.name || `${kinds[vessel.kind] || 'Okręt'} #${vessel.id}`;
    const marker = L.marker([point[1], point[0]], { pane: 'worldShips', icon: L.divIcon({ html: symbol, className: 'world-ship-marker', iconSize: [26, 26], iconAnchor: [13, 13] }) })
      .bindTooltip(iconTip(icon, label, [`Państwo: ${vessel.country || 'brak danych'}${vessel.own ? ' (Twoje)' : ''}`, `Stan: ${statuses[vessel.status] || vessel.status}`, `Życie: ${vessel.health}/100`]), { direction: 'top', className: 'world-tooltip' }).addTo(map);
    if (route) marker.on('tooltipopen', () => route.addTo(map)).on('tooltipclose', () => route.remove());
    vessels.push([vessel, marker]);
  }
  if (vessels.length && window.GameTradeNavigation) setInterval(() => { const now = gameTime(); for (const [vessel, marker] of vessels) { const p = window.GameTradeNavigation.position(vessel, now); if (p) marker.setLatLng([p[1], p[0]]); } }, 1000);
  if (window.ResizeObserver) new ResizeObserver(() => map.invalidateSize()).observe(document.getElementById('world-map'));
}).catch(error => { console.error('Ekran Świat:', error); say('Nie udało się wczytać mapy świata. Odśwież stronę.'); });
})();
