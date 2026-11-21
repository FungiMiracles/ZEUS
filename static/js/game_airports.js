/* 20 Nov 2026: porty lotnicze na ekranie „Infrastruktura i energetyka”.
   21 Nov 2026: osobna zakładka „Transport lotniczy” z własną mapą (miasta państwa + lotniska); mapa regionów nie pokazuje już lotnisk.
   - tooltip miasta (game_infrastructure.js → GameAirports.cityContent) z przyciskiem „Zbuduj port lotniczy”;
   - okno budowy: żuraw i samolot, nazwa (≤ 60 znaków), koszt w surowcach, chipach i ROI (ludność × 100), 14 dni Entendy;
   - ikona samolotu obok miasta z lotniskiem: w budowie — tooltip z postępem; czynne — nazwa i przycisk „Zarządzaj”
     (lista połączeń lotniczych z możliwością czasowego zawieszenia każdego z nich). */
(() => {
    'use strict';
    const node = document.getElementById('airport-config');
    if (!node) return;
    let state = JSON.parse(node.textContent);
    const config = {stateUrl: state.stateUrl, changeUrl: state.changeUrl, csrf: state.csrf, airplaneIcon: state.airplaneIcon,
                    craneIcon: state.craneIcon, materialIcons: state.materialIcons || {}, countriesUrl: state.countriesUrl};
    const make = (tag, text, cls) => { const el = document.createElement(tag); if (text != null) el.textContent = text; if (cls) el.className = cls; return el; };
    const image = (src, cls) => { const img = make('img', null, cls); img.src = src; img.alt = ''; return img; };
    const number = value => new Intl.NumberFormat('pl-PL').format(value);
    const money = value => window.GameMoney ? window.GameMoney.format(value, false) : `${number(value)} ROI`;
    const dateText = value => value ? new Intl.DateTimeFormat('pl-PL', {timeZone: 'UTC', dateStyle: 'short', timeStyle: 'short'}).format(new Date(value)) : '—';
    const uuid = () => crypto.randomUUID ? crypto.randomUUID() : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => { const r = crypto.getRandomValues(new Uint8Array(1))[0] & 15; return (c === 'x' ? r : r & 3 | 8).toString(16); });
    const status = document.getElementById('airport-map-status');
    const say = text => { if (status) { status.textContent = text; status.hidden = !text; } };
    let map = null, layer = null, cityLayer = null, fitted = false;

    async function post(payload) {
        const response = await fetch(config.changeUrl, {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': config.csrf}, body: JSON.stringify(payload)});
        const result = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(result.error || 'Operacja nie powiodła się.');
        return result;
    }
    async function refresh() {
        try {
            const response = await fetch(config.stateUrl, {credentials: 'same-origin', cache: 'no-store'});
            if (!response.ok) return;
            state = await response.json();
            summary(); drawCities(); draw();
        } catch {}
    }
    const cityOf = id => (state.cities || []).find(city => String(city.id) === String(id));
    const airportOf = id => (state.airports || []).find(airport => String(airport.cityId) === String(id));

    /** Treść tooltipa miasta: nazwa, ludność, lotnisko albo przycisk budowy. */
    // 20 Nov 2026: tooltipy w stylu gry (biała karta, granatowy akcent, przyciski jak na ekranie infrastruktury)
    function tip(title, subtitle, icon) {
        const box = make('div', null, 'airport-tip'), head = make('div', null, 'airport-tip-head'), text = make('div');
        if (icon) head.append(image(icon));
        text.append(make('strong', title)); if (subtitle) text.append(make('span', subtitle));
        head.append(text); box.append(head); return box;
    }
    function action(label, handler, primary = true, icon = null) {
        const button = make('button', null, 'airport-tip-button' + (primary ? '' : ' airport-tip-secondary')); button.type = 'button';
        if (icon) button.append(image(icon));
        button.append(document.createTextNode(label));
        button.addEventListener('click', event => { event.stopPropagation(); handler(); });
        return button;
    }
    /** Treść tooltipa miasta: nazwa, ludność, lotnisko albo przycisk budowy. */
    function cityContent(cityId, name) {
        const city = cityOf(cityId), airport = airportOf(cityId);
        const box = tip(name, city ? `Ludność: ${number(city.population)}` : null);
        if (airport) {
            box.append(make('p', airport.completed ? `Port lotniczy: ${airport.name}` : `Budowa portu lotniczego: ${airport.progress}%`, 'airport-tip-line'));
        } else if (state.available && city && city.eligible && !city.hasAirport) {
            const actions = make('div', null, 'airport-tip-actions');
            actions.append(action('Zbuduj port lotniczy', () => openBuild(city), true, config.airplaneIcon));
            box.append(actions);
        } else if (state.available && city && !city.eligible) {
            box.append(make('p', `Port lotniczy można zbudować w mieście powyżej ${number(state.minPopulation)} mieszkańców.`, 'airport-tip-line airport-note'));
        }
        return box;
    }

    // ---------- budowa ----------
    const buildDialog = document.getElementById('airport-build-dialog'), buildForm = document.getElementById('airport-build-form');
    const nameInput = document.getElementById('airport-name'), nameCount = document.getElementById('airport-name-count');
    let building = null, buildKey = null;
    function updateCount() { nameCount.textContent = `${nameInput.value.length} / ${state.nameMax || 60}`; }
    nameInput.addEventListener('input', updateCount);
    function openBuild(city) {
        window.GameRegionTooltip?.close(map);
        building = city; buildKey = uuid();
        document.getElementById('airport-build-title').textContent = `Budowa portu lotniczego — ${city.name}`;
        document.getElementById('airport-build-city').textContent = `Miasto: ${city.name} · ludność ${number(city.population)}`;
        nameInput.value = city.defaultName; nameInput.maxLength = state.nameMax || 60; updateCount();
        const list = document.getElementById('airport-materials'); list.replaceChildren();
        let missing = false;
        for (const item of state.materials || []) {
            const row = make('li', null, 'airport-material' + (item.have < item.need ? ' airport-material-missing' : ''));
            if (config.materialIcons[item.code]) row.append(image(config.materialIcons[item.code]));
            row.append(make('span', item.label), make('strong', `${number(item.need)}`), make('small', `w magazynie: ${number(item.have)}`));
            list.append(row); if (item.have < item.need) missing = true;
        }
        const cost = Number(city.cost), funds = Number(state.funds || 0);
        document.getElementById('airport-cost').textContent = money(city.cost);
        document.getElementById('airport-funds').textContent = money(state.funds || '0');
        document.getElementById('airport-days').textContent = `${state.buildDays} dni Entendy`;
        const warning = document.getElementById('airport-build-warning');
        warning.textContent = [missing ? 'Za mało surowców lub chipów w magazynie.' : '', cost > funds ? 'Za mało niewydanych środków w budżecie infrastruktury.' : ''].filter(Boolean).join(' ');
        warning.hidden = !warning.textContent;
        document.getElementById('airport-build-error').textContent = '';
        document.getElementById('airport-build-confirm').disabled = missing || cost > funds;
        buildDialog.showModal();
    }
    document.getElementById('airport-build-cancel').onclick = () => buildDialog.close();
    buildForm.addEventListener('submit', async event => {
        event.preventDefault();
        if (!building) return;
        const button = document.getElementById('airport-build-confirm'); button.disabled = true;
        try {
            const name = nameInput.value.trim();
            if (!name) throw new Error('Podaj nazwę portu lotniczego.');
            const result = await post({action: 'build', city_id: building.id, name, expected_cost: building.cost, request_id: buildKey});
            buildDialog.close();
            say(`Rozpoczęto budowę: ${result.airport.name}. Ukończenie (Entenda): ${dateText(result.airport.readyAt)}.`);
            await refresh();
        } catch (error) { document.getElementById('airport-build-error').textContent = error.message; button.disabled = false; }
    });

    // ---------- zarządzanie ----------
    const manageDialog = document.getElementById('airport-manage-dialog');
    let managed = null;
    document.getElementById('airport-manage-close').onclick = () => manageDialog.close();
    function openManage(airport) {
        window.GameRegionTooltip?.close(map);
        managed = airport.id; renderManage(); manageDialog.showModal();
    }
    function renderManage() {
        const airport = (state.airports || []).find(a => a.id === managed);
        const routesBox = document.getElementById('airport-routes'); routesBox.replaceChildren();
        if (!airport) { document.getElementById('airport-manage-summary').textContent = 'Lotnisko nie jest już dostępne.'; return; }
        document.getElementById('airport-manage-title').textContent = airport.name;
        const routes = airport.routes || [], active = routes.filter(r => r.active);
        const income = active.reduce((sum, r) => sum + Number(r.bonus), 0);
        document.getElementById('airport-manage-summary').textContent =
            `${airport.cityName} · czynne połączenia: ${active.length} z ${routes.length} · dochód z połączeń tego lotniska: ${money(String(income))} / cykl budżetowy`;
        if (!routes.length) { routesBox.append(make('p', 'Brak innych czynnych lotnisk na świecie — połączenia powstaną automatycznie, gdy zostaną zbudowane.')); return; }
        const table = make('table', null, 'airport-routes-table');
        const head = make('tr'); for (const label of ['Lotnisko docelowe', 'Państwo', 'Odległość', 'Dochód / cykl', 'Stan', '']) head.append(make('th', label));
        const thead = make('thead'); thead.append(head); table.append(thead);
        const body = make('tbody');
        for (const route of routes) {
            const row = make('tr', null, route.active ? '' : 'airport-route-suspended');
            const destination = make('td'); destination.append(make('strong', route.name), make('small', route.cityName));
            const state_ = route.suspendedByMe ? 'Zawieszone' : route.suspendedByOther ? 'Zawieszone przez drugą stronę' : 'Czynne';
            row.append(destination, make('td', route.country), make('td', `${number(route.distanceKm)} km`), make('td', money(route.bonus)));
            const stateCell = make('td'); stateCell.append(make('span', state_, 'airport-route-state')); row.append(stateCell);
            const cell = make('td'), button = make('button', route.suspendedByMe ? 'Wznów' : 'Zawieś'); button.type = 'button';
            button.title = route.suspendedByMe ? 'Przywróć połączenie' : 'Czasowo zawieś połączenie (można je wznowić)';
            button.addEventListener('click', async () => {
                button.disabled = true; document.getElementById('airport-manage-error').textContent = '';
                try { await post({action: route.suspendedByMe ? 'resume' : 'suspend', airport_id: airport.id, other_id: route.otherId}); await refresh(); renderManage(); }
                catch (error) { document.getElementById('airport-manage-error').textContent = error.message; button.disabled = false; }
            });
            cell.append(button); row.append(cell); body.append(row);
        }
        table.append(body); routesBox.append(table);
    }

    // ---------- zmiana nazwy (najwyżej raz na rok Entendy) ----------
    const renameDialog = document.getElementById('airport-rename-dialog'), renameInput = document.getElementById('airport-rename-name'), renameCount = document.getElementById('airport-rename-count');
    let renaming = null;
    const updateRenameCount = () => { renameCount.textContent = `${renameInput.value.length} / ${state.nameMax || 60}`; };
    renameInput.addEventListener('input', updateRenameCount);
    function openRename(airport) {
        window.GameRegionTooltip?.close(map);
        if (manageDialog.open) manageDialog.close();
        renaming = airport;
        document.getElementById('airport-rename-current').textContent = `Obecna nazwa: ${airport.name}`;
        renameInput.value = airport.name; renameInput.maxLength = state.nameMax || 60; updateRenameCount();
        const warning = document.getElementById('airport-rename-warning');
        warning.textContent = airport.canRename ? '' : `Nazwę zmieniono ${dateText(airport.renamedAt)} (Entenda). Kolejna zmiana będzie możliwa ${dateText(airport.renameAvailableAt)} (Entenda).`;
        warning.hidden = !warning.textContent;
        renameInput.disabled = !airport.canRename;
        document.getElementById('airport-rename-confirm').disabled = !airport.canRename;
        document.getElementById('airport-rename-error').textContent = '';
        renameDialog.showModal();
    }
    document.getElementById('airport-rename-cancel').onclick = () => renameDialog.close();
    document.getElementById('airport-manage-rename').onclick = () => { const airport = (state.airports || []).find(a => a.id === managed); if (airport) openRename(airport); };
    document.getElementById('airport-rename-form').addEventListener('submit', async event => {
        event.preventDefault();
        if (!renaming) return;
        const button = document.getElementById('airport-rename-confirm'); button.disabled = true;
        try {
            const name = renameInput.value.trim();
            if (!name) throw new Error('Podaj nową nazwę portu lotniczego.');
            const result = await post({action: 'rename', airport_id: renaming.id, name});
            renameDialog.close();
            say(`Zmieniono nazwę lotniska na: ${result.airport.name}.`);
            await refresh();
        } catch (error) { document.getElementById('airport-rename-error').textContent = error.message; button.disabled = false; }
    });

    // ---------- znaczniki lotnisk przy miastach ----------
    function airportContent(airport) {
        const box = tip(airport.name, airport.completed ? `${airport.cityName} · port lotniczy czynny` : `${airport.cityName} · w budowie`, config.airplaneIcon);
        if (!airport.completed) {
            const row = make('div', null, 'airport-tip-progress');
            row.append(image(config.craneIcon), make('span', `Budowa: ${airport.progress}%`), make('small', `ukończenie ${dateText(airport.readyAt)} (Entenda)`));
            const bar = make('progress'); bar.max = 100; bar.value = airport.progress; bar.setAttribute('aria-label', 'Postęp budowy lotniska');
            box.append(row, bar);
        } else {
            const routes = airport.routes || [];
            const facts = make('dl', null, 'airport-tip-facts');
            const fact = (label, value) => { const row = make('div'); row.append(make('dt', label), make('dd', value)); facts.append(row); };
            fact('Czynne połączenia', `${routes.filter(r => r.active).length} z ${routes.length}`);
            if (airport.health < 100) fact('Życie', `${airport.health} / 100`);
            box.append(facts);
        }
        const actions = make('div', null, 'airport-tip-actions');
        if (airport.completed) actions.append(action('Zarządzaj', () => openManage(airport)));
        actions.append(action('Zmień nazwę', () => openRename(airport), !airport.completed));
        box.append(actions);
        return box;
    }
    function draw() {
        if (!map) return;
        layer.clearLayers();
        for (const airport of state.airports || []) {
            const badge = make('div', null, 'airport-map-badge' + (airport.completed ? '' : ' airport-map-building'));
            badge.append(image(config.airplaneIcon));
            if (!airport.completed) badge.append(image(config.craneIcon, 'airport-map-crane'));
            const label = airport.completed ? airport.name : `${airport.name} — budowa ${airport.progress}%`;
            const marker = L.marker([airport.position[1], airport.position[0]], {pane: 'infrastructureAirports', title: label, alt: label, riseOnHover: true,
                icon: L.divIcon({html: badge, className: 'airport-map-marker', iconSize: [30, 30], iconAnchor: [-7, 15]})}).addTo(layer);
            if (window.GameRegionTooltip) window.GameRegionTooltip.bind(marker, () => airportContent(airport), {className: 'airport-leaflet-tooltip'});
            else marker.bindTooltip(airportContent(airport));
            if (airport.completed) marker.on('click', () => openManage(airport));
        }
    }
    // ---------- zakładka „Transport lotniczy”: podsumowanie, mapa państwa i miasta ----------
    function summary() {
        const set = (id, text) => { const el = document.getElementById(id); if (el) el.textContent = text; };
        const own = state.airports || [];
        set('airport-count', `${own.filter(a => a.completed).length} czynne · ${own.filter(a => !a.completed).length} w budowie`);
        set('airport-world', number(state.worldAirports || 0));
        set('airport-income', money(state.income || '0'));
        set('airport-funds-summary', money(state.funds || '0'));
        const noTech = document.getElementById('airport-no-tech'); if (noTech) noTech.hidden = !!state.available;
    }
    function drawCities() {
        if (!map) return;
        cityLayer.clearLayers();
        for (const city of state.cities || []) {
            if (!city.point) continue;
            const marker = L.circleMarker([city.point[1], city.point[0]], {pane: 'airportCities', radius: city.eligible ? 5.5 : 4,
                color: '#22301f', weight: 1.6, fillColor: city.eligible ? '#ffffff' : '#c9ced6', fillOpacity: 1});
            if (window.GameRegionTooltip) window.GameRegionTooltip.bind(marker, () => cityContent(city.id, city.name), {className: 'airport-leaflet-tooltip'});
            else marker.bindTooltip(city.name, {direction: 'top'});
            marker.addTo(cityLayer);
        }
    }
    function fit() {
        if (fitted || !map) return;
        const size = map.getSize(); if (!size.x || !size.y) return;
        const points = (state.cities || []).filter(c => c.point).map(c => L.latLng(c.point[1], c.point[0]));
        if (!points.length) return;
        map.fitBounds(L.latLngBounds(points).pad(.25), {maxZoom: 4, animate: false}); fitted = true;
    }
    function init() {
        const element = document.getElementById('airport-map');
        if (map || !element || !window.L) return;
        map = L.map(element, {crs: L.CRS.Simple, minZoom: -10, maxZoom: 8, zoomSnap: .25, attributionControl: false});
        map.setView([0, 0], 0);
        if (config.countriesUrl) fetch(config.countriesUrl, {credentials: 'same-origin'}).then(r => r.json()).then(countries => {
            L.geoJSON(countries, {coordsToLatLng: c => L.latLng(c[1], c[0]), interactive: false,
                style: f => ({color: '#667C63', weight: 1, fillOpacity: 1, fillColor: Number(f.properties?.panstwo_id) === state.countryId ? '#B8C9B0' : '#F1F2EE'})}).addTo(map).bringToBack();
        }).catch(() => say('Nie udało się wczytać granic państw.'));
        map.createPane('airportCities').style.zIndex = '450';
        map.createPane('infrastructureAirports').style.zIndex = '640';
        cityLayer = L.layerGroup().addTo(map); layer = L.layerGroup().addTo(map);
        drawCities(); draw(); fit();
        if (window.ResizeObserver) new ResizeObserver(() => { map.invalidateSize(); fit(); }).observe(element);
        if ((state.airports || []).some(a => !a.completed)) setInterval(() => { if (!document.hidden && !buildDialog.open && !manageDialog.open && !renameDialog.open) refresh(); }, 60000);
    }
    summary();
    // Mapa tworzona przy pierwszym otwarciu zakładki (ukryty kontener ma zerowy rozmiar).
    const open = () => requestAnimationFrame(() => { init(); map?.invalidateSize(); fit(); });
    document.getElementById('infrastructure-tab-air')?.addEventListener('click', open);
    if (document.getElementById('infrastructure-air-panel') && !document.getElementById('infrastructure-air-panel').hidden) open();
    window.GameAirports = {cityContent, refresh};
})();
