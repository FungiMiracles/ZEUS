(() => {
'use strict';
// 13 Nov 2026: mapa panelu państwa — ciemne morze, ląd #F8F9F6, regiony #B8C9B0 (granice #667C63, najechany #D5E5C6,
// wybrany #E8B65C), miasta białe z ciemną obwódką, stolica #D99A26; obiekty z map obrony/wojny/infrastruktury z filtrami.
const node = document.getElementById('panel-map-config');
if (!node) return;
const config = JSON.parse(node.textContent);
const status = document.getElementById('game-map-status');
const resetButton = document.getElementById('game-map-reset');
const say = text => { status.textContent = text; status.hidden = false; };
if (config.countryId == null) { say('Do konta nie przypisano państwa.'); return; }
if (!window.L) { say('Nie udało się załadować biblioteki mapy.'); return; }

const COLORS = { land: '#F8F9F6', landBorder: '#c9cec4', region: '#B8C9B0', border: '#667C63', hover: '#D5E5C6', selected: '#E8B65C',
                 city: '#FFFFFF', cityBorder: '#22301f', capital: '#D99A26', road: '#7a5a2e' };
const make = (tag, text, cls) => { const el = document.createElement(tag); if (text != null) el.textContent = text; if (cls) el.className = cls; return el; };
const number = value => value == null ? 'brak danych' : Number(value).toLocaleString('pl-PL');
const coordinates = c => L.latLng(c[1], c[0]);
const map = L.map('game-country-map', { crs: L.CRS.Simple, minZoom: -10, maxZoom: 8, zoomSnap: 0.25, zoomDelta: 0.5, attributionControl: false });
const load = url => fetch(url, { credentials: 'same-origin' }).then(r => { if (!r.ok) throw new Error(r.status); return r.json(); });

// ---- filtry obiektów ----
const filterKey = `panel-map-filters:v1:${config.countryId}`;
const buttons = [...document.querySelectorAll('[data-panel-filter]')];
const allKinds = buttons.map(b => b.dataset.panelFilter);
let active = new Set(allKinds);
try { const saved = JSON.parse(localStorage.getItem(filterKey)); if (Array.isArray(saved)) active = new Set(saved.filter(k => allKinds.includes(k))); } catch {}
const layers = Object.fromEntries(allKinds.map(kind => [kind, L.layerGroup()]));
function applyFilters() {
  for (const button of buttons) button.setAttribute('aria-pressed', String(active.has(button.dataset.panelFilter)));
  for (const [kind, layer] of Object.entries(layers)) { if (active.has(kind)) layer.addTo(map); else layer.remove(); }
  const all = document.getElementById('panel-filters-all');
  if (all) all.textContent = active.size ? 'Odznacz wszystkie' : 'Zaznacz wszystkie';
  try { localStorage.setItem(filterKey, JSON.stringify([...active])); } catch {}
}
for (const button of buttons) button.addEventListener('click', () => { const kind = button.dataset.panelFilter; active.has(kind) ? active.delete(kind) : active.add(kind); applyFilters(); });
document.getElementById('panel-filters-all')?.addEventListener('click', () => { active = active.size ? new Set() : new Set(allKinds); applyFilters(); });

// ---- obiekty ----
map.createPane('panelRoads'); map.getPane('panelRoads').style.zIndex = '420';
map.createPane('panelObjects'); map.getPane('panelObjects').style.zIndex = '620';
map.createPane('panelDefenses'); map.getPane('panelDefenses').style.zIndex = '630';
const regionDefenses = [];
// Środek ciężkości największego wielokąta regionu (gdy leży wewnątrz regionu) — punkt dla obrony regionu.
function regionCenter(geometry) {
  const polygons = geometry?.type === 'Polygon' ? [geometry.coordinates] : geometry?.type === 'MultiPolygon' ? geometry.coordinates : [];
  const area = ring => ring.reduce((sum, p, i) => { const q = ring[(i + 1) % ring.length]; return sum + p[0] * q[1] - q[0] * p[1]; }, 0) / 2;
  const outer = polygons.filter(p => p?.[0]?.length > 2).sort((a, b) => Math.abs(area(b[0])) - Math.abs(area(a[0])))[0];
  if (!outer) return null;
  const ring = outer[0], a = area(ring); if (!a) return null;
  let x = 0, y = 0;
  ring.forEach((p, i) => { const q = ring[(i + 1) % ring.length], f = p[0] * q[1] - q[0] * p[1]; x += (p[0] + q[0]) * f; y += (p[1] + q[1]) * f; });
  const c = [x / (6 * a), y / (6 * a)];
  const inside = r => { let hit = false; for (let i = 0, j = r.length - 1; i < r.length; j = i++) { const [xi, yi] = r[i], [xj, yj] = r[j]; if ((yi > c[1]) !== (yj > c[1]) && c[0] < (xj - xi) * (c[1] - yi) / (yj - yi) + xi) hit = !hit; } return hit; };
  return inside(ring) && !outer.slice(1).some(inside) ? c : null;
}
for (const item of config.objects || []) {
  const layer = layers[item.kind]; if (!layer) continue;
  if (item.path) {
    L.polyline(item.path.map(p => [p[1], p[0]]), { pane: 'panelRoads', color: COLORS.road, weight: 3, opacity: .85 })
      .bindTooltip(make('span', item.name), { sticky: true, className: 'panel-map-tooltip' }).addTo(layer);
    continue;
  }
  // Obrona przeciwrakietowa obiektu stoi w tym samym punkcie co broniony obiekt — mniejsza plakietka w jego prawym górnym rogu,
  // w warstwie obiektu (widoczna tylko z nim). 19 Nov 2026: obrona regionu — plakietka wyśrodkowana w punkcie regionu.
  const defense = !!item.defense, regionDefense = item.defense === 'region';
  const symbol = make('div', null, 'panel-map-object' + (defense ? ' is-defense' : '') + (regionDefense ? ' is-region-defense' : '')); const img = make('img'); img.src = item.icon; img.alt = ''; symbol.append(img);
  if (!defense && item.health != null && item.health < 100) { const bar = make('i', null, 'panel-map-health'); bar.style.width = Math.max(0, Math.min(100, item.health)) + '%'; symbol.append(bar); }
  const tip = make('div'); tip.append(make('strong', item.name)); if (item.health != null) tip.append(make('div', `Życie: ${Math.round(item.health)}/100`));
  const size = defense && !regionDefense ? [17, 17] : [28, 28], anchor = defense && !regionDefense ? [-6, 24] : [14, 14];
  const marker = L.marker([item.position[1], item.position[0]], { pane: defense ? 'panelDefenses' : 'panelObjects', icon: L.divIcon({ html: symbol, className: 'panel-map-marker', iconSize: size, iconAnchor: anchor }) })
    .bindTooltip(tip, { direction: 'top', offset: [0, -14], className: 'panel-map-tooltip' }).addTo(layer);
  if (regionDefense) regionDefenses.push([item.regionId, marker]);
}

// ---- regiony, ląd, miasta ----
const own = id => Object.prototype.hasOwnProperty.call(config.regionNames, String(id));
let selected = null;
Promise.all([load(config.regionsUrl), load(config.countriesUrl).catch(() => null)]).then(([regions, countries]) => {
  if (countries) L.geoJSON(countries, { coordsToLatLng: coordinates, interactive: false,
    style: { color: COLORS.landBorder, weight: 1, fillColor: COLORS.land, fillOpacity: 1 } }).addTo(map);
  const baseStyle = { color: COLORS.border, weight: 1.4, fillColor: COLORS.region, fillOpacity: 1 };
  const regionLayer = L.geoJSON(regions, {
    coordsToLatLng: coordinates, filter: f => own(f.properties?.region_id), style: () => ({ ...baseStyle }),
    onEachFeature: (feature, layer) => {
      const id = String(feature.properties.region_id), info = (config.regions || {})[id] || {};
      const tip = make('div'); tip.append(make('strong', config.regionNames[id] || `Region #${id}`),
        make('div', `Populacja: ${number(info.population)}`), make('div', `Średnia infrastruktura: ${info.infrastructure == null ? 'brak danych' : String(info.infrastructure).replace('.', ',') + ' / 100'}`));
      layer.bindTooltip(tip, { sticky: true, direction: 'auto', offset: L.point(16, 0), className: 'panel-map-tooltip' });
      layer.on('mouseover', () => { if (selected !== layer) layer.setStyle({ fillColor: COLORS.hover, weight: 2.2 }); });
      layer.on('mouseout', () => { if (selected !== layer) layer.setStyle({ ...baseStyle }); });
      layer.on('click', () => {
        if (selected && selected !== layer) selected.setStyle({ ...baseStyle });
        selected = selected === layer ? null : layer;
        layer.setStyle(selected ? { fillColor: COLORS.selected, weight: 2.4 } : { ...baseStyle });
      });
    }
  }).addTo(map);
  const centers = new Map(regions.features?.map(f => [String(f.properties?.region_id), f.geometry]) || []);
  for (const [regionId, marker] of regionDefenses) { const c = centers.has(regionId) && regionCenter(centers.get(regionId)); if (c) marker.setLatLng([c[1], c[0]]); }
  function focusCountry() {
    map.invalidateSize();
    const bounds = regionLayer.getBounds();
    if (bounds.isValid()) { map.fitBounds(bounds, { padding: [35, 35], maxZoom: 5, animate: false }); return true; }
    return false;
  }
  const ok = focusCountry();
  resetButton.disabled = !ok; resetButton.addEventListener('click', focusCountry);
  if (!ok) say('Brak geometrii zarządzanego państwa. Wyświetlono świat.');

  map.createPane('panelCities'); map.getPane('panelCities').style.zIndex = '610';
  load(config.citiesUrl).then(cities => {
    L.geoJSON(cities, {
      coordsToLatLng: coordinates, filter: f => Object.prototype.hasOwnProperty.call(config.cities, String(f.properties.miasto_id)),
      pointToLayer: (feature, latlng) => {
        const city = config.cities[String(feature.properties.miasto_id)];
        return L.circleMarker(latlng, { pane: 'panelCities', radius: city.stolica ? 7 : 4.5, color: COLORS.cityBorder, weight: 1.6,
                                         fillColor: city.stolica ? COLORS.capital : COLORS.city, fillOpacity: 1 });
      },
      onEachFeature: (feature, layer) => {
        const city = config.cities[String(feature.properties.miasto_id)];
        const tip = make('div', null, 'panel-city-tip'), icon = make('img'); icon.src = config.cityIcon; icon.alt = '';
        const text = make('div'); text.append(make('strong', city.stolica ? `${city.nazwa} — stolica` : city.nazwa), make('div', `Populacja: ${number(city.populacja)}`));
        tip.append(icon, text);
        layer.bindTooltip(tip, { direction: 'auto', offset: L.point(12, 0), className: 'panel-map-tooltip' });
        layer.on('mouseover', () => layer.setRadius(city.stolica ? 9 : 6.5));
        layer.on('mouseout', () => layer.setRadius(city.stolica ? 7 : 4.5));
      }
    }).addTo(layers.cities || map);
  }).catch(() => say('Mapa została wczytana, ale nie udało się wyświetlić miast.'));
  applyFilters();
  if (window.ResizeObserver) new ResizeObserver(() => map.invalidateSize()).observe(document.getElementById('game-country-map'));
}).catch(error => { console.error('Błąd mapy panelu gry:', error); say('Nie udało się wczytać mapy. Odśwież stronę, aby spróbować ponownie.'); });
})();
