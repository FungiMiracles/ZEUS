/* Lokalizacja magazynu państwa (22 Nov 2026): okno z mapą do wskazania miasta magazynu (obowiązkowe po zatwierdzeniu
   pierwszego budżetu; zmiana lokalizacji z ekranu handlu) oraz ikona magazynu obok miasta na mapach właściciela. */
(() => {
  'use strict';
  const make = (tag, text, cls) => { const el = document.createElement(tag); if (text != null) el.textContent = text; if (cls) el.className = cls; return el; };

  // Ikona magazynu obok miasta (panel państwa, świat, handel) — tylko dla państwa-właściciela.
  function marker(map, warehouse, options = {}) {
    if (!map || !window.L || !warehouse || !warehouse.point) return null;
    const badge = make('div', null, 'warehouse-map-badge'); const img = make('img'); img.src = warehouse.icon; img.alt = 'Magazyn'; badge.append(img);
    // 22 Nov 2026: `pane` tylko, gdy podany — `pane: undefined` nadpisuje domyślny markerPane i Leaflet rzuca wyjątek
    // (na panelu państwa przerywało to rysowanie miast).
    const markerOptions = { keyboard: false, interactive: true, zIndexOffset: 900,
      icon: L.divIcon({ html: badge, className: 'warehouse-map-marker', iconSize: [24, 24], iconAnchor: [-5, 26] }) };
    if (options.pane) markerOptions.pane = options.pane;
    return L.marker([warehouse.point[1], warehouse.point[0]], markerOptions)
      .bindTooltip(`Magazyn państwa — ${warehouse.name}`, { direction: 'top', className: options.tooltipClass || 'world-tooltip' })
      .addTo(options.layer || map);
  }

  const node = document.getElementById('warehouse-config');
  let config = null;
  try { config = node ? JSON.parse(node.textContent) : null; } catch { config = null; }
  const dialog = document.getElementById('warehouse-dialog');
  let map = null, selected = null, cityLayer = null;

  function select(id) {
    selected = config.cities.find(city => city.id === Number(id)) || null;
    const list = document.getElementById('warehouse-city-select'); if (list && selected) list.value = String(selected.id);
    document.getElementById('warehouse-choice').textContent = selected ? `Wybrane miasto: ${selected.name}${selected.capital ? ' (stolica)' : ''}` : 'Kliknij miasto na mapie albo wybierz je z listy.';
    document.getElementById('warehouse-save').disabled = !selected;
    if (cityLayer) cityLayer.eachLayer(layer => layer.setStyle?.({ fillColor: layer.cityId === selected?.id ? '#E8B65C' : layer.capital ? '#D99A26' : '#fff', radius: layer.cityId === selected?.id ? 8 : 5 }));
  }

  function buildMap() {
    if (map || !window.L) return;
    const box = document.getElementById('warehouse-map');
    map = L.map(box, { crs: L.CRS.Simple, minZoom: -10, maxZoom: 8, zoomSnap: .25, attributionControl: false });
    map.setView([0, 0], 0);
    const own = new Set(config.cities.map(city => String(city.regionId)));
    fetch(config.regionsUrl, { credentials: 'same-origin' }).then(r => { if (!r.ok) throw new Error(); return r.json(); }).then(data => {
      L.geoJSON(data, { coordsToLatLng: p => L.latLng(p[1], p[0]), interactive: false,
        style: f => own.has(String(f.properties?.region_id)) ? { color: '#667C63', weight: .8, fillColor: '#B8C9B0', fillOpacity: 1 } : { color: '#c9cec4', weight: .4, fillColor: '#eef0ea', fillOpacity: 1 } }).addTo(map);
      cityLayer.bringToFront?.();
    }).catch(() => { document.getElementById('warehouse-error').textContent = 'Nie udało się wczytać mapy — wybierz miasto z listy.'; });
    cityLayer = L.featureGroup().addTo(map);
    for (const city of config.cities) {
      const dot = L.circleMarker([city.point[1], city.point[0]], { radius: 5, color: '#22301f', weight: 1.2, fillColor: city.capital ? '#D99A26' : '#fff', fillOpacity: 1 })
        .bindTooltip(`${city.name}${city.capital ? ' (stolica)' : ''} · ${city.population.toLocaleString('pl-PL')} mieszk.`, { direction: 'top' })
        .on('click', () => select(city.id)).addTo(cityLayer);
      dot.cityId = city.id; dot.capital = city.capital;
    }
    if (cityLayer.getBounds().isValid()) map.fitBounds(cityLayer.getBounds(), { padding: [30, 30], maxZoom: 4 });
    if (window.ResizeObserver) new ResizeObserver(() => map.invalidateSize()).observe(box);
  }

  function open() {
    if (!config || !dialog) return;
    const list = document.getElementById('warehouse-city-select');
    if (list && !list.options.length) {
      list.append(new Option('— wybierz miasto —', ''));
      for (const city of config.cities) list.append(new Option(`${city.name}${city.capital ? ' (stolica)' : ''}`, String(city.id)));
      list.onchange = () => select(list.value);
    }
    if (!dialog.open) dialog.showModal();
    buildMap(); setTimeout(() => map?.invalidateSize(), 50);
    select(selected?.id ?? config.current ?? '');
  }

  if (config && dialog) {
    document.getElementById('warehouse-cancel')?.addEventListener('click', () => dialog.close());
    dialog.addEventListener('cancel', event => { if (config.required) event.preventDefault(); });
    document.getElementById('warehouse-save').addEventListener('click', async () => {
      if (!selected) return;
      const button = document.getElementById('warehouse-save'), error = document.getElementById('warehouse-error');
      button.disabled = true; error.textContent = '';
      try {
        const response = await fetch(config.saveUrl, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': config.csrf }, body: JSON.stringify({ city_id: selected.id }) });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || 'Nie udało się zapisać lokalizacji magazynu.');
        window.location.reload();
      } catch (exc) { error.textContent = exc.message; button.disabled = false; }
    });
    for (const button of document.querySelectorAll('[data-warehouse-open]')) button.addEventListener('click', open);
    if (config.required) open();
  }

  window.GameWarehouse = { marker, open };
})();
