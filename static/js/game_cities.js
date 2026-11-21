/* 21 Nov 2026: zakładka „Miasta” (obiekty miejskie, etap 1) na ekranie „Infrastruktura i energetyka”.
   - mapa państwa: miasta jako ikony MIASTO.svg z nazwą (bez kropek), stolica na złoto; kliknięcie otwiera zarządzanie;
   - okno miasta: budżety sektorów, katalog obiektów, plan 8×8 kratek (przeciąganie albo klik obiektu, potem kratki);
   - po upuszczeniu obiektu: okno z kosztem budowy i rocznym utrzymaniem („Buduj” / „Anuluj”);
   - kliknięcie zbudowanego obiektu: szczegóły i likwidacja (zwrot 25% kosztu budowy do budżetu sektora). */
(() => {
    'use strict';
    const node = document.getElementById('city-config');
    if (!node) return;
    let state = JSON.parse(node.textContent);
    const cfg = {stateUrl: state.stateUrl, quoteUrl: state.quoteUrl, changeUrl: state.changeUrl, csrf: state.csrf, countriesUrl: state.countriesUrl,
                 cityIcon: state.cityIcon, craneIcon: state.craneIcon, icons: state.icons || {}, sectorIcons: state.sectorIcons || {}};
    const $ = id => document.getElementById(id);
    const make = (tag, text, cls) => { const el = document.createElement(tag); if (text != null) el.textContent = text; if (cls) el.className = cls; return el; };
    const image = (src, cls) => { const img = make('img', null, cls); img.src = src; img.alt = ''; return img; };
    const number = value => new Intl.NumberFormat('pl-PL').format(Number(value || 0));
    const money = value => window.GameMoney ? window.GameMoney.format(value, false) : `${number(value)} ROI`;
    const pct = value => `${Number(value || 0).toLocaleString('pl-PL', {maximumFractionDigits: 1})}%`;
    const dateText = value => value ? new Intl.DateTimeFormat('pl-PL', {timeZone: 'UTC', dateStyle: 'short'}).format(new Date(value)) : '—';
    const uuid = () => crypto.randomUUID ? crypto.randomUUID() : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => { const r = crypto.getRandomValues(new Uint8Array(1))[0] & 15; return (c === 'x' ? r : r & 3 | 8).toString(16); });
    const say = text => { const el = $('city-map-status'); el.textContent = text || ''; el.hidden = !text; };
    const rule = kind => (state.catalog || []).find(item => item.kind === kind);
    const cityOf = id => (state.cities || []).find(city => city.id === id);
    let map = null, markers = null, fitted = false, current = null, picked = null, pending = null, busy = false, demolishing = null;

    async function api(url, body) {
        const options = body ? {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': cfg.csrf}, body: JSON.stringify(body)} : {cache: 'no-store'};
        const response = await fetch(url, {credentials: 'same-origin', ...options});
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || 'Operacja nie powiodła się.');
        return data;
    }
    async function refresh() {
        const data = await api(cfg.stateUrl);
        state = {...state, ...data};
        renderIndicators(); drawCities();
        if (current && $('city-dialog').open) renderDialog();
    }

    // ---------- kontenery wskaźników (lewa strona mapy) ----------
    function renderIndicators() {
        const percent = state.coverage?.percent || {};
        for (const code of ['education', 'health', 'transport']) {
            $('city-pct-' + code).textContent = pct(percent[code]);
            $('city-bar-' + code).value = Math.min(100, Number(percent[code] || 0));
        }
        const facts = $('city-facts'); facts.replaceChildren();
        const fact = (label, value) => { const row = make('div'); row.append(make('dt', label), make('dd', value)); facts.append(row); };
        fact('Ludność miejska', number(state.coverage?.urbanPopulation));
        fact('Poziom edukacji', `${state.education ?? '—'} / 100`);
        fact('Szybszy rozwój technologii', state.researchBonus ? `−${pct(state.researchBonus)} czasu` : 'od poziomu edukacji 51');
        fact('Dodatek żłobków do przyrostu', `+${Number(state.coverage?.nurseryBonus || 0).toLocaleString('pl-PL', {minimumFractionDigits: 2})} pkt proc.`);
        for (const [label, value] of Object.entries(state.coverage?.effects || {})) if (value) fact(`Efekt obiektów: ${label.toLowerCase()}`, `+${value}`);
    }

    // ---------- mapa ----------
    function cityMarker(city) {
        const box = make('div', null, 'city-marker' + (city.capital ? ' city-marker-capital' : ''));
        const icon = make('span', null, 'city-marker-icon'); const mask = `url("${cfg.cityIcon}")`;
        icon.style.webkitMaskImage = mask; icon.style.maskImage = mask;
        const building = (city.buildings || []).some(b => !b.completed);
        box.append(icon, make('span', city.name, 'city-marker-name'));
        if (building) box.append(image(cfg.craneIcon, 'city-marker-crane'));
        return L.marker([city.point[1], city.point[0]], {pane: 'cityMarkers', keyboard: true, title: city.name, alt: city.name, riseOnHover: true,
            icon: L.divIcon({html: box, className: 'city-marker-wrap', iconSize: [24, 24], iconAnchor: [12, 12]})});
    }
    function drawCities() {
        if (!map) return;
        markers.clearLayers();
        for (const city of state.cities || []) {
            if (!city.point) continue;
            const marker = cityMarker(city).addTo(markers);
            const tip = make('div'); tip.append(make('strong', city.capital ? `${city.name} (stolica)` : city.name), make('div', `Ludność: ${number(city.population)}`));
            const count = (city.buildings || []).length; tip.append(make('div', count ? `Obiekty miejskie: ${count}` : 'Brak obiektów miejskich'));
            marker.bindTooltip(tip, {direction: 'top', offset: [0, -12], className: 'city-leaflet-tooltip'});
            marker.on('click', () => openCity(city.id));
        }
    }
    function fit() {
        if (fitted || !map) return;
        const size = map.getSize(); if (!size.x || !size.y) return;
        const points = (state.cities || []).filter(c => c.point).map(c => L.latLng(c.point[1], c.point[0]));
        if (!points.length) return;
        map.fitBounds(L.latLngBounds(points).pad(.2), {maxZoom: 4, animate: false}); fitted = true;
    }
    function init() {
        if (map || !window.L) return;
        map = L.map('city-map', {crs: L.CRS.Simple, minZoom: -10, maxZoom: 8, zoomSnap: .25, attributionControl: false});
        map.setView([0, 0], 0);
        fetch(cfg.countriesUrl, {credentials: 'same-origin'}).then(r => r.json()).then(countries => {
            L.geoJSON(countries, {coordsToLatLng: c => L.latLng(c[1], c[0]), interactive: false,
                style: f => ({color: '#667C63', weight: 1, fillOpacity: 1, fillColor: Number(f.properties?.panstwo_id) === state.countryId ? '#B8C9B0' : '#F1F2EE'})}).addTo(map).bringToBack();
        }).catch(() => say('Nie udało się wczytać granic państw.'));
        map.createPane('cityMarkers').style.zIndex = '640';
        markers = L.layerGroup().addTo(map);
        const zoomClass = () => map.getContainer().classList.toggle('city-map-far', map.getZoom() < 1.5);
        map.on('zoomend', zoomClass); zoomClass();
        drawCities(); fit();
        if (window.ResizeObserver) new ResizeObserver(() => { map.invalidateSize(); fit(); }).observe($('city-map'));
    }

    // ---------- okno zarządzania miastem ----------
    const dialog = $('city-dialog');
    $('city-dialog-close').onclick = () => dialog.close();
    dialog.addEventListener('close', () => { picked = null; current = null; });
    function openCity(id) {
        current = id; picked = null;
        $('city-dialog-error').textContent = '';
        renderDialog(); dialog.showModal();
    }
    function renderDialog() {
        const city = cityOf(current);
        if (!city) { dialog.close(); return; }
        $('city-dialog-title').textContent = city.capital ? `${city.name} — stolica` : city.name;
        $('city-dialog-population').textContent = `Ludność: ${number(city.population)}`;
        $('city-dialog-icon').classList.toggle('is-capital', !!city.capital);
        // budżety: ochrona zdrowia, edukacja, infrastruktura (dostępne do wydania w bieżącym okresie)
        const budgets = $('city-budgets'); budgets.replaceChildren();
        for (const code of ['healthcare', 'education', 'infrastructure']) {
            const box = make('div', null, 'city-budget');
            if (cfg.sectorIcons[code]) box.append(image(cfg.sectorIcons[code]));
            const text = make('div'); text.append(make('span', state.sectors?.[code] || code), make('strong', money(state.funds?.[code] || '0')));
            box.append(text); budgets.append(box);
        }
        // katalog obiektów
        const catalog = $('city-catalog'); catalog.replaceChildren();
        for (const item of state.catalog || []) {
            const card = make('button', null, 'city-object' + (picked === item.kind ? ' is-picked' : '')); card.type = 'button';
            card.draggable = true; card.dataset.kind = item.kind; card.setAttribute('role', 'listitem');
            card.setAttribute('aria-pressed', String(picked === item.kind));
            card.title = `${item.label}: koszt ${money(item.cost)}, utrzymanie ${money(item.maintenance)} rocznie, ${item.days} dni Entendy. ${item.effect}`;
            card.append(image(cfg.icons[item.kind], 'city-object-icon'));
            const text = make('div', null, 'city-object-text');
            text.append(make('strong', item.label), make('span', `Budowa: ${money(item.cost)} · ${item.days} dni`),
                        make('span', `Utrzymanie: ${money(item.maintenance)} / rok`),
                        make('span', item.served ? `Obsługuje: ${number(item.served)} mieszk.` : 'Obsługuje: nie dotyczy'),
                        make('small', `Finansowanie: ${item.sectorLabel.toLowerCase()}`));
            card.append(text);
            card.addEventListener('click', () => { picked = picked === item.kind ? null : item.kind; renderDialog(); });
            card.addEventListener('dragstart', event => { event.dataTransfer.setData('text/plain', item.kind); event.dataTransfer.effectAllowed = 'copy'; picked = item.kind; });
            catalog.append(card);
        }
        $('city-catalog-hint').textContent = picked ? `Wybrano: ${rule(picked)?.label}. Kliknij wolną kratkę planu miasta.` : 'Przeciągnij obiekt na wolną kratkę albo kliknij obiekt, a potem kratkę.';
        // plan miasta 8×8
        const grid = $('city-grid'); grid.replaceChildren();
        const size = state.grid || 8, taken = new Map((city.buildings || []).map(b => [b.cell, b]));
        for (let cell = 0; cell < size * size; cell++) {
            const building = taken.get(cell);
            const box = make('button', null, 'city-cell' + (building ? ' is-built' + (building.completed ? '' : ' is-building') : '') + (picked && !building ? ' is-target' : ''));
            box.type = 'button'; box.dataset.cell = String(cell); box.setAttribute('role', 'gridcell');
            const label = `Kratka ${Math.floor(cell / size) + 1}–${cell % size + 1}`;
            if (building) {
                box.append(image(cfg.icons[building.kind], 'city-cell-icon'));
                if (!building.completed) {
                    box.append(image(cfg.craneIcon, 'city-cell-crane'));
                    const bar = make('span', null, 'city-cell-progress'); bar.style.setProperty('--progress', `${building.progress}%`); box.append(bar);
                }
                box.title = `${building.label}${building.completed ? '' : ` — budowa ${building.progress}%, ukończenie ${dateText(building.readyAt)} (Entenda)`}`;
                box.setAttribute('aria-label', `${label}: ${box.title}`);
                box.addEventListener('click', () => openDemolish(building));
            } else {
                box.setAttribute('aria-label', `${label}: wolna`);
                box.addEventListener('click', () => { if (picked) askBuild(picked, cell); else $('city-dialog-error').textContent = 'Najpierw wybierz obiekt do postawienia.'; });
                box.addEventListener('dragover', event => { event.preventDefault(); event.dataTransfer.dropEffect = 'copy'; box.classList.add('is-over'); });
                box.addEventListener('dragleave', () => box.classList.remove('is-over'));
                box.addEventListener('drop', event => { event.preventDefault(); box.classList.remove('is-over'); const kind = event.dataTransfer.getData('text/plain') || picked; if (kind) askBuild(kind, cell); });
            }
            grid.append(box);
        }
    }

    // ---------- budowa: potwierdzenie z kosztem i utrzymaniem ----------
    const buildDialog = $('city-build-dialog');
    $('city-build-cancel').onclick = () => buildDialog.close();
    async function askBuild(kind, cell) {
        if (busy) return;
        const item = rule(kind), city = cityOf(current); if (!item || !city) return;
        $('city-dialog-error').textContent = '';
        busy = true;
        try {
            const quote = await api(cfg.quoteUrl, {kind, city_id: city.id, cell});
            pending = {kind, cell, cityId: city.id, cost: quote.cost, key: uuid()};
            $('city-build-icon').src = cfg.icons[kind];
            $('city-build-title').textContent = `Budowa: ${item.label}`;
            $('city-build-city').textContent = `${city.name} · kratka ${Math.floor(cell / (state.grid || 8)) + 1}–${cell % (state.grid || 8) + 1}`;
            $('city-build-cost').textContent = money(quote.cost);
            $('city-build-upkeep').textContent = money(quote.maintenance);
            $('city-build-days').textContent = `${quote.days} dni Entendy`;
            $('city-build-served').textContent = quote.served ? `${number(quote.served)} mieszk.` : 'nie dotyczy';
            const reserveText = Number(quote.fromReserve) > 0 ? ` Brakującą część — ${money(quote.fromReserve)} — pokryje rezerwa budżetowa (dostępne ${money(quote.reserve)}).` : '';
            $('city-build-funding').textContent = `Finansowanie: budżet „${quote.sectorLabel}” (dostępne ${money(quote.available)}).${reserveText} Roczne utrzymanie będzie pobierane z tego budżetu przy zatwierdzaniu kolejnych budżetów.`;
            $('city-build-effect').textContent = `Efekt: ${quote.effect}`;
            $('city-build-error').textContent = quote.affordable ? '' : 'Budżet sektora i rezerwa budżetowa łącznie nie pokrywają kosztu budowy.';
            $('city-build-confirm').disabled = !quote.affordable;
            buildDialog.showModal();
        } catch (error) { $('city-dialog-error').textContent = error.message; }
        finally { busy = false; }
    }
    $('city-build-form').addEventListener('submit', async event => {
        event.preventDefault();
        if (!pending || busy) return;
        busy = true; const button = $('city-build-confirm'); button.disabled = true;
        try {
            const result = await api(cfg.changeUrl, {action: 'build', kind: pending.kind, city_id: pending.cityId, cell: pending.cell, expected_cost: pending.cost, request_id: pending.key});
            buildDialog.close(); picked = null; pending = null;
            say(`Rozpoczęto budowę: ${result.building.label}. Ukończenie (Entenda): ${dateText(result.building.readyAt)}.`);
            await refresh();
        } catch (error) { $('city-build-error').textContent = error.message; button.disabled = false; }
        finally { busy = false; }
    });

    // ---------- szczegóły i likwidacja ----------
    const demolishDialog = $('city-demolish-dialog');
    $('city-demolish-cancel').onclick = () => demolishDialog.close();
    function openDemolish(building) {
        demolishing = building;
        const item = rule(building.kind) || {};
        $('city-demolish-icon').src = cfg.icons[building.kind];
        $('city-demolish-title').textContent = building.label;
        $('city-demolish-info').textContent = building.completed
            ? `Obiekt działa. Roczne utrzymanie: ${money(building.maintenance)} (${(item.sectorLabel || '').toLowerCase()}). ${item.effect || ''}`
            : `Budowa: ${building.progress}% · ukończenie ${dateText(building.readyAt)} (Entenda).`;
        $('city-demolish-refund').textContent = `Likwidacja zwraca 25% kosztu budowy — ${money(building.refund)} — do budżetu „${item.sectorLabel || ''}”. Efekty obiektu zostaną usunięte.`;
        $('city-demolish-error').textContent = '';
        $('city-demolish-confirm').disabled = false;
        demolishDialog.showModal();
    }
    $('city-demolish-form').addEventListener('submit', async event => {
        event.preventDefault();
        if (!demolishing || busy) return;
        busy = true; const button = $('city-demolish-confirm'); button.disabled = true;
        try {
            const data = await api(cfg.changeUrl, {action: 'demolish', building_id: demolishing.id});
            demolishDialog.close();
            say(`Zlikwidowano obiekt: ${demolishing.label}. Zwrot: ${money(data.result.refund)}.`);
            demolishing = null; await refresh();
        } catch (error) { $('city-demolish-error').textContent = error.message; button.disabled = false; }
        finally { busy = false; }
    });

    renderIndicators();
    const open = () => requestAnimationFrame(() => { init(); map?.invalidateSize(); fit(); });
    $('infrastructure-tab-cities')?.addEventListener('click', open);
    if ($('infrastructure-cities-panel') && !$('infrastructure-cities-panel').hidden) open();
    setInterval(() => {
        if (!document.hidden && !busy && !buildDialog.open && !demolishDialog.open && !$('infrastructure-cities-panel')?.hidden
            && (state.cities || []).some(c => (c.buildings || []).some(b => !b.completed))) refresh().catch(() => {});
    }, 60000);
})();
