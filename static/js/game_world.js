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
  const regionLayer = L.geoJSON(regions, { pane: 'worldRegions', coordsToLatLng: coordinates, style: regionStyle, filter: f => !!config.regions[String(f.properties?.region_id)],
    onEachFeature: (feature, layer) => {
      const id = String(feature.properties.region_id), r = config.regions[id], occupied = config.occupied[id];
      const owner = config.countries[String(r.countryId)];
      const lines = [`Populacja: ${mln(r.population)}`]; if (owner) lines.push(`Państwo: ${owner.name}`); if (occupied) lines.push(`Okupowany przez: ${occupied.occupier || 'nieznane państwo'}`);
      layer.bindTooltip(iconTip(config.regionIcon, r.name, lines), tipOptions);
      layer.on('mouseover', () => layer.setStyle({ fillColor: C.hover })); layer.on('mouseout', () => regionLayer.resetStyle(layer));
    } }).addTo(regional);
  L.geoJSON(countries, { pane: 'worldBorders', coordsToLatLng: coordinates, interactive: false, style: { color: C.border, weight: 2, fill: false } }).addTo(regional);
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
  function setView(view) { if (view === 'regional') { political.remove(); regional.addTo(map); } else { regional.remove(); political.addTo(map); }
    document.querySelector('.legend-regional').hidden = view !== 'regional'; try { localStorage.setItem('world-view', view); } catch {} }
  let saved = 'political'; try { saved = localStorage.getItem('world-view') || 'political'; } catch {}
  for (const radio of document.querySelectorAll('[name="world-view"]')) { radio.checked = radio.value === saved; radio.addEventListener('change', () => setView(radio.value)); }
  setView(saved);
  const fit = () => { map.invalidateSize(); if (bounds.isValid()) map.fitBounds(bounds, { padding: [20, 20], animate: false }); };
  fit(); document.getElementById('world-map-reset').addEventListener('click', fit);
  // --- miasta ---
  load(config.citiesUrl).then(cities => {
    L.geoJSON(cities, { pane: 'worldCities', coordsToLatLng: coordinates, filter: f => !!config.cities[String(f.properties?.miasto_id)],
      pointToLayer: (feature, latlng) => {
        const city = config.cities[String(feature.properties.miasto_id)], p = Number(city.population) || 0;
        const radius = p > 5e6 ? 6 : p >= 1e6 ? 4 : 2.5;
        return L.circleMarker(latlng, { pane: 'worldCities', radius, color: C.cityBorder, weight: 1.2, fillColor: city.capital ? C.capital : C.city, fillOpacity: 1 });
      },
      onEachFeature: (feature, layer) => {
        const city = config.cities[String(feature.properties.miasto_id)];
        layer.bindTooltip(iconTip(config.cityIcon, city.name, [`Populacja: ${mln(city.population)}`, `Rodzaj: ${city.type || 'brak danych'}`, `Portowe: ${city.port ? 'tak' : 'nie'}`]), { direction: 'auto', offset: L.point(10, 0), className: 'world-tooltip' });
      } }).addTo(map);
  }).catch(() => say('Mapa została wczytana, ale nie udało się wyświetlić miast.'));
  if (window.ResizeObserver) new ResizeObserver(() => map.invalidateSize()).observe(document.getElementById('world-map'));
}).catch(error => { console.error('Ekran Świat:', error); say('Nie udało się wczytać mapy świata. Odśwież stronę.'); });
})();
