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
// 26 Nov 2026: satelity szpiegowskie (własne; obce — gdy państwo ma satelitę na orbicie) i obiekty rozpoznane przez satelity
window.GameSatellites?.attach(map, { mode: 'world', filterHost: document.getElementById('world-satellite-filters'), filterStyle: 'checkbox' });
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
  // 18 Nov 2026: znaczniki przy miastach (np. siedziba MFW) — osobna warstwa z przełącznikiem zapamiętywanym w przeglądarce;
  // kolejne znaczniki wystarczy dodać do cityMarkersLayer.
  const markersToggle = document.getElementById('world-markers-toggle');
  if (!map.getPane('worldCityMarkers')) { map.createPane('worldCityMarkers'); map.getPane('worldCityMarkers').style.zIndex = '660'; }
  const cityMarkersLayer = L.layerGroup();
  // 22 Nov 2026: magazyn własnego państwa; 23 Nov 2026: także magazyny innych państw — osobny filtr „Magazyny”
  const warehouseLayer = L.layerGroup(), warehousesToggle = document.getElementById('world-warehouses-toggle');
  window.GameWarehouse?.marker(map, config.warehouse, { pane: 'worldCityMarkers', layer: warehouseLayer });
  for (const item of config.foreignWarehouses || []) window.GameWarehouse?.marker(map, item, { pane: 'worldCityMarkers', layer: warehouseLayer, label: `Magazyn: ${item.country} — ${item.name}`, flag: item.flag });
  let showWarehouses = true; try { showWarehouses = localStorage.getItem('world-warehouses') !== '0'; } catch {}
  const applyWarehouses = () => { if (showWarehouses) warehouseLayer.addTo(map); else warehouseLayer.remove(); try { localStorage.setItem('world-warehouses', showWarehouses ? '1' : '0'); } catch {} };
  if (warehousesToggle) { warehousesToggle.checked = showWarehouses; warehousesToggle.addEventListener('change', () => { showWarehouses = warehousesToggle.checked; applyWarehouses(); }); }
  applyWarehouses();
  let showMarkers = true; try { showMarkers = localStorage.getItem('world-city-markers') !== '0'; } catch {}
  if (showMarkers) cityMarkersLayer.addTo(map);
  if (markersToggle) {
    markersToggle.checked = showMarkers;
    markersToggle.addEventListener('change', () => {
      try { localStorage.setItem('world-city-markers', markersToggle.checked ? '1' : '0'); } catch {}
      if (markersToggle.checked) cityMarkersLayer.addTo(map); else cityMarkersLayer.remove();
    });
  }
  let imfBadge = null;
  load(config.citiesUrl).then(cities => {
    citiesLayer = L.geoJSON(cities, { pane: 'worldCities', coordsToLatLng: coordinates, filter: f => !!config.cities[String(f.properties?.miasto_id)],
      pointToLayer: (feature, latlng) => {
        const city = config.cities[String(feature.properties.miasto_id)], p = Number(city.population) || 0;
        const radius = p > 5e6 ? 6 : p >= 1e6 ? 4 : 2.5;
        const imfCity = config.imf && String(feature.properties.miasto_id) === String(config.imf.cityId);
        return L.circleMarker(latlng, { pane: 'worldCities', radius, color: C.cityBorder, weight: 1.2, fillColor: city.capital ? C.capital : C.city, fillOpacity: 1, className: imfCity ? 'world-imf-city' : '' });
      },
      onEachFeature: (feature, layer) => {
        const city = config.cities[String(feature.properties.miasto_id)];
        // 18 Nov 2026: Port Loyab — siedziba Międzynarodowego Funduszu Walutowego; kliknięcie (dotknięcie) otwiera ekran MFW.
        const imf = config.imf && config.imf.cityId != null && String(feature.properties.miasto_id) === String(config.imf.cityId);
        const lines = [`Populacja: ${mln(city.population)}`, `Rodzaj: ${city.type || 'brak danych'}`, `Portowe: ${city.port ? 'tak' : 'nie'}`];
        const tip = iconTip(config.cityIcon, city.name, lines);
        if (imf) {
          const link = document.createElement('a'); link.href = config.imf.url; link.className = 'world-imf-link';
          link.textContent = 'Międzynarodowy Fundusz Walutowy →';
          const hint = document.createElement('small'); hint.className = 'world-imf-hint'; hint.textContent = 'Kliknij miasto, aby otworzyć ekran MFW';
          tip.lastChild.append(link, hint);
          layer.on('click', () => { window.location.href = config.imf.url; });
          // 18 Nov 2026: półprzezroczysty znacznik siedziby MFW obok miasta (jeden, mimo zdublowanych punktów w danych mapy)
          if (!imfBadge && config.imf.icon) {
            const badge = make('div', null, 'world-imf-badge'); const badgeImg = make('img'); badgeImg.src = config.imf.icon; badgeImg.alt = ''; badge.append(badgeImg, make('span', 'MFW'));
            imfBadge = L.marker(layer.getLatLng(), { pane: 'worldCityMarkers', keyboard: true, title: 'Międzynarodowy Fundusz Walutowy', icon: L.divIcon({ html: badge, className: 'world-imf-badge-marker', iconSize: [68, 28], iconAnchor: [-8, 14] }) })
              .bindTooltip('Międzynarodowy Fundusz Walutowy — Port Loyab', { direction: 'top', className: 'world-tooltip' })
              .on('click', () => { window.location.href = config.imf.url; }).addTo(cityMarkersLayer);
          }
        }
        // 21 Nov 2026: kliknięcie miasta otwiera okno obiektów miejskich (game_cities.js; cudze miasta tylko do odczytu)
        if (!imf && window.GameCities) {
          const hint = document.createElement('small'); hint.className = 'world-city-hint'; hint.textContent = 'Kliknij, aby zobaczyć obiekty miejskie';
          tip.lastChild.append(hint);
          layer.on('click', () => window.GameCities.open(feature.properties.miasto_id));
        }
        layer.bindTooltip(tip, { direction: 'auto', offset: L.point(10, 0), className: 'world-tooltip' + (imf ? ' world-imf-tooltip' : ''), interactive: imf });
      } });
    if (!citiesToggle || citiesToggle.checked) citiesLayer.addTo(map);
  }).catch(() => say('Mapa została wczytana, ale nie udało się wyświetlić miast.'));
  // --- koleje (19 Nov 2026): tory wszystkich państw i pociągi 120 km/h; przełącznik „Koleje” zapamiętywany w przeglądarce ---
  if (window.GameRailTrains && (config.rails || []).length) {
    // 20 Nov 2026: koleje pod kropkami miast (worldCities 600) — wcześniej ten sam z-index i tory zasłaniały miasta.
    for (const [name, z] of [['worldRails', '560'], ['worldTrains', '570'], ['worldRailCranes', '580']]) { if (!map.getPane(name)) { map.createPane(name); map.getPane(name).style.zIndex = z; } }
    map.getPane('worldTrains').style.pointerEvents = 'none';
    const railLayer = L.layerGroup(), trainLayer = L.layerGroup();
    const dateText = v => v ? new Intl.DateTimeFormat('pl-PL', { timeZone: 'UTC', dateStyle: 'short', timeStyle: 'short' }).format(new Date(v)) : '—';
    for (const line of config.rails) {
      window.GameRailTrains.track(line.path, { pane: 'worldRails', faded: !line.completed }).addTo(railLayer);
      const lines = [`${line.countries.filter(Boolean).join(' · ')}`, `${Math.round(Number(line.distanceKm)).toLocaleString('pl-PL')} km`,
                     line.completed ? 'Linia czynna' : `Budowa torów: ${line.progress}% · ukończenie ${dateText(line.readyAt)}`];
      const tip = iconTip(config.railIcon || config.landIcon, `Kolej: ${line.cityAName} – ${line.cityBName}`, lines);   // 23 Nov 2026: KOLEJ.svg
      L.polyline(line.path.map(p => [p[1], p[0]]), { pane: 'worldRails', color: '#000', weight: 12, opacity: 0 }).bindTooltip(tip, { sticky: true, className: 'world-tooltip' }).addTo(railLayer);
      if (!line.completed && config.craneIcon) {
        const mid = line.path[Math.floor(line.path.length / 2)], box = make('div', null, 'rail-crane'), img = make('img'); img.src = config.craneIcon; img.alt = ''; box.append(img);
        L.marker([mid[1], mid[0]], { pane: 'worldRailCranes', icon: L.divIcon({ html: box, className: 'rail-crane-marker', iconSize: [20, 20], iconAnchor: [10, 10] }) })
          .bindTooltip(iconTip(config.craneIcon, `Budowa kolei: ${line.cityAName} – ${line.cityBName}`, [`Postęp: ${line.progress}%`, `Ukończenie: ${dateText(line.readyAt)}`]), { direction: 'top', className: 'world-tooltip' }).addTo(railLayer);
      }
    }
    window.GameRailTrains.trains(map, config.rails, { pane: 'worldTrains', layer: trainLayer, gameNow: config.gameNow, timeMultiplier: config.timeMultiplier, speed: config.trainSpeed });
    // 20 Nov 2026: osobny filtr „Pociągi” — pociągi widoczne tylko przy włączonych kolejach i włączonym filtrze.
    const railsToggle = document.getElementById('world-rails-toggle'), trainsToggle = document.getElementById('world-trains-toggle');
    let showRails = true, showTrains = true;
    try { showRails = localStorage.getItem('world-rails') !== '0'; showTrains = localStorage.getItem('world-trains') !== '0'; } catch {}
    const apply = () => {
      if (showRails) railLayer.addTo(map); else railLayer.remove();
      if (showRails && showTrains) trainLayer.addTo(map); else trainLayer.remove();
      if (trainsToggle) { trainsToggle.disabled = !showRails; trainsToggle.closest('label')?.classList.toggle('is-disabled', !showRails); }
      try { localStorage.setItem('world-rails', showRails ? '1' : '0'); localStorage.setItem('world-trains', showTrains ? '1' : '0'); } catch {}
    };
    if (railsToggle) { railsToggle.checked = showRails; railsToggle.addEventListener('change', () => { showRails = railsToggle.checked; apply(); }); }
    if (trainsToggle) { trainsToggle.checked = showTrains; trainsToggle.addEventListener('change', () => { showTrains = trainsToggle.checked; apply(); }); }
    apply();
  } else for (const id of ['world-rails-toggle', 'world-trains-toggle']) document.getElementById(id)?.closest('label')?.setAttribute('hidden', '');
  // --- lotnictwo (20 Nov 2026): porty lotnicze przy miastach (warstwa „Znaczniki miast”) i samoloty między nimi (filtr „Samoloty”) ---
  const air = config.air || {};
  for (const airport of air.airports || []) {
    const box = make('div', null, 'world-airport'), img = make('img'); img.src = config.airplaneIcon; img.alt = ''; box.append(img);
    L.marker([airport.position[1], airport.position[0]], { pane: 'worldCityMarkers', keyboard: false, icon: L.divIcon({ html: box, className: 'world-airport-marker', iconSize: [16, 16], iconAnchor: [-5, 8] }) })
      .bindTooltip(iconTip(config.airplaneIcon, airport.name, [`${airport.cityName} · ${airport.country}`]), { direction: 'top', className: 'world-tooltip' }).addTo(cityMarkersLayer);
  }
  const planesToggle = document.getElementById('world-planes-toggle');
  if (window.GameAirTraffic && (air.routes || []).length) {
    if (!map.getPane('worldPlanes')) { map.createPane('worldPlanes'); map.getPane('worldPlanes').style.zIndex = '650'; }
    const planeLayer = L.layerGroup();
    window.GameAirTraffic.planes(map, air, { pane: 'worldPlanes', layer: planeLayer, gameNow: config.gameNow, timeMultiplier: config.timeMultiplier, speed: air.speed, icon: config.airplaneIcon });
    let showPlanes = true; try { showPlanes = localStorage.getItem('world-planes') !== '0'; } catch {}
    const applyPlanes = () => { if (showPlanes) planeLayer.addTo(map); else planeLayer.remove(); try { localStorage.setItem('world-planes', showPlanes ? '1' : '0'); } catch {} };
    if (planesToggle) { planesToggle.checked = showPlanes; planesToggle.addEventListener('change', () => { showPlanes = planesToggle.checked; applyPlanes(); }); }
    applyPlanes();
  } else planesToggle?.closest('label')?.setAttribute('hidden', '');
  // --- płynące statki towarowe ---
  map.createPane('worldShips'); map.getPane('worldShips').style.zIndex = '640';
  const anchor = Date.parse(config.gameNow), realAnchor = performance.now(), gameTime = () => anchor + (performance.now() - realAnchor) * (config.timeMultiplier || 1);
  // 23 Nov 2026: filtr „Obiekty na morzu” — okręty wojenne, lotniskowce, okręty podwodne i statki handlowe (przesyłka na odcinku
  // kolejowym lub lotniczym pozostaje widoczna jako pociąg / samolot).
  const seaLayer = L.layerGroup(), seaToggle = document.getElementById('world-sea-toggle');
  let showSea = true; try { showSea = localStorage.getItem('world-sea') !== '0'; } catch {}
  const seaVisible = (marker, mode) => { const hide = !showSea && mode !== 'land' && mode !== 'air'; if (hide) marker.remove(); else if (!map.hasLayer(marker)) marker.addTo(map); };
  const ships = [];
  for (const ship of config.ships || []) {
    L.polyline((ship.route || [ship.source, ship.target]).map(p => [p[1], p[0]]), { pane: 'worldShips', color: '#ffffff', weight: 1, opacity: .35, dashArray: '4 6', interactive: false }).addTo(seaLayer);
    // 22 Nov 2026: przesyłka z odcinkami — pociąg towarowy (pomarańczowy, paczka, flaga sprzedającego), statek albo samolot
    const point = window.GameTradeNavigation?.position(ship, gameTime()); if (!point) continue;
    const shipIcon = mode => {
      if (mode === 'land') return L.divIcon({ html: window.GameTradeNavigation.trainSymbol(ship), className: 'world-ship-marker', iconSize: [28, 28], iconAnchor: [14, 14] });
      const air = mode === 'air', symbol = make('div', null, 'world-ship'); const img = make('img'); img.src = air ? config.airplaneIcon : config.shipIcon; img.alt = ''; symbol.append(img);
      if (ship.flag) { const flag = make('img', null, 'world-ship-flag'); flag.src = ship.flag; flag.alt = ''; symbol.append(flag); }
      return L.divIcon({ html: symbol, className: 'world-ship-marker', iconSize: [26, 26], iconAnchor: [13, 13] });
    };
    const tip = () => { const mode = window.GameTradeNavigation.mode(ship, gameTime()), air = mode === 'air', land = mode === 'land';
      return iconTip(air ? config.airplaneIcon : land ? '/static/icons/PACZKA.svg' : config.shipIcon, air ? 'Samolot towarowy' : land ? 'Pociąg towarowy' : 'Statek towarowy', [`${ship.seller || '?'} → ${ship.buyer || '?'}`, `Dostawa do magazynu: ${new Intl.DateTimeFormat('pl-PL', { timeZone: 'UTC', dateStyle: 'short', timeStyle: 'short' }).format(new Date(ship.arrivesAt))}`]); };
    const marker = L.marker([point[1], point[0]], { pane: 'worldShips', icon: L.divIcon({ html: make('div'), className: 'world-ship-marker' }) }).bindTooltip(tip, { direction: 'top', className: 'world-tooltip' }).addTo(map);
    seaVisible(marker, window.GameTradeNavigation.syncIcon(marker, ship, gameTime(), shipIcon)); marker._shipIcon = shipIcon;
    ships.push([ship, marker]);
  }
  if (ships.length && window.GameTradeNavigation) setInterval(() => { const now = gameTime(); for (const [ship, marker] of ships) { if (now >= Date.parse(ship.arrivesAt)) { marker.remove(); marker._done = true; continue; } const p = window.GameTradeNavigation.position(ship, now); if (p) marker.setLatLng([p[1], p[0]]); seaVisible(marker, window.GameTradeNavigation.syncIcon(marker, ship, now, marker._shipIcon)); } }, 1000);
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
      .bindTooltip(iconTip(icon, label, [`Państwo: ${vessel.country || 'brak danych'}${vessel.own ? ' (Twoje)' : ''}`, `Stan: ${statuses[vessel.status] || vessel.status}`, `Życie: ${vessel.health}/100`]), { direction: 'top', className: 'world-tooltip' }).addTo(seaLayer);
    if (route) marker.on('tooltipopen', () => route.addTo(map)).on('tooltipclose', () => route.remove());
    vessels.push([vessel, marker]);
  }
  const applySea = () => {
    if (showSea) seaLayer.addTo(map); else seaLayer.remove();
    for (const [ship, marker] of ships) if (!marker._done) seaVisible(marker, window.GameTradeNavigation?.mode(ship, gameTime()));
    try { localStorage.setItem('world-sea', showSea ? '1' : '0'); } catch {}
  };
  if (seaToggle) { seaToggle.checked = showSea; seaToggle.addEventListener('change', () => { showSea = seaToggle.checked; applySea(); }); }
  applySea();
  if (vessels.length && window.GameTradeNavigation) setInterval(() => { const now = gameTime(); for (const [vessel, marker] of vessels) { const p = window.GameTradeNavigation.position(vessel, now); if (p) marker.setLatLng([p[1], p[0]]); } }, 1000);
  if (window.ResizeObserver) new ResizeObserver(() => map.invalidateSize()).observe(document.getElementById('world-map'));
}).catch(error => { console.error('Ekran Świat:', error); say('Nie udało się wczytać mapy świata. Odśwież stronę.'); });
})();
