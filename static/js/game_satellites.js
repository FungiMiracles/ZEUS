/* 26 Nov 2026: satelity szpiegowskie na mapach (ekrany „Świat”, „Wywiad wojskowy”, „Obrona państwa”, panel wojenny).
   GameSatellites.attach(map, {mode, csrf, filterHost, filterStyle}) — satelity w białym kole z czarną obwódką (ikona lotu
   i flaga właściciela), rozpoznane obiekty (warstwa „Rozpoznanie satelitarne”), filtry, a na ekranie wywiadu — opcje misji
   w kole wokół własnego satelity i lista misji. GameSatellites.launch(base, csrf, done) — okno wynoszenia satelity na orbitę
   (pasek postępu przez minutę; okna nie można zamknąć przed końcem operacji). */
(() => {
    'use strict';
    const STATE_URL = '/game/satelity/stan';
    let state = null, anchor = 0, realAnchor = 0;
    const views = [];
    const make = (tag, text, cls) => { const node = document.createElement(tag); if (text != null) node.textContent = text; if (cls) node.className = cls; return node; };
    const img = (src, cls) => { const node = make('img', null, cls); node.src = src; node.alt = ''; return node; };
    const money = value => { const n = Number(value || 0); return n >= 1e9 ? (n / 1e9).toLocaleString('pl-PL', { maximumFractionDigits: 2 }) + ' mld ROI' : (n / 1e6).toLocaleString('pl-PL', { maximumFractionDigits: 1 }) + ' mln ROI'; };
    const when = value => value ? new Intl.DateTimeFormat('pl-PL', { timeZone: 'UTC', dateStyle: 'short', timeStyle: 'short' }).format(new Date(value)) : '—';
    const uuid = () => crypto.randomUUID ? crypto.randomUUID() : 'xxxxxxxx-xxxx-4xxx-8xxx-xxxxxxxxxxxx'.replace(/x/g, () => (Math.random() * 16 | 0).toString(16));
    const gameTime = () => anchor + (performance.now() - realAnchor) * (state?.timeMultiplier || 1);
    const latlng = point => L.latLng(point[1], point[0]);
    const FILTER_KEYS = { satellites: 'game-satellites-filter:satellites', intel: 'game-satellites-filter:intel' };
    const filterOn = kind => { try { return localStorage.getItem(FILTER_KEYS[kind]) !== '0'; } catch { return true; } };
    const setFilter = (kind, value) => { try { localStorage.setItem(FILTER_KEYS[kind], value ? '1' : '0'); } catch { } };

    function position(sat, now) {
        if (sat.status === 'launching') return now >= Date.parse(sat.orbitAt) ? sat.from : null;
        const start = Date.parse(sat.segStart), end = Date.parse(sat.segEnd);
        if (now >= end) return sat.to;
        if (now <= start) return sat.from;
        const share = (now - start) / (end - start);
        return [sat.from[0] + (sat.to[0] - sat.from[0]) * share, sat.from[1] + (sat.to[1] - sat.from[1]) * share];
    }

    async function load() {
        const response = await fetch(STATE_URL, { credentials: 'same-origin', cache: 'no-store' });
        if (!response.ok) throw new Error('Nie udało się wczytać satelitów.');
        state = await response.json(); anchor = Date.parse(state.gameNow); realAnchor = performance.now();
        for (const view of views) view.render();
        return state;
    }
    async function post(url, body, csrf) {
        const response = await fetch(url, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf || '' }, body: JSON.stringify(body) });
        let data; try { data = await response.json(); } catch { throw new Error('Nie udało się połączyć z serwerem gry.'); }
        if (!response.ok) throw new Error(data.error || 'Operacja nie powiodła się.');
        return data;
    }

    // ---------------- okna ----------------
    function dialog(title, icon) {
        const box = make('dialog', null, 'satellite-dialog');
        const form = make('form'); form.method = 'dialog';
        const head = make('h2', null, 'satellite-dialog-title'); if (icon) head.append(img(icon)); head.append(make('span', title));
        const body = make('div', null, 'satellite-dialog-body'), error = make('p', null, 'satellite-dialog-error'), actions = make('div', null, 'satellite-dialog-actions');
        error.setAttribute('role', 'alert');
        form.append(head, body, error, actions); box.append(form); document.body.append(box);
        box.addEventListener('close', () => box.remove());
        return { box, form, body, error, actions };
    }

    function chooseCountry(sat, mission, csrf) {
        const d = dialog(`${mission.label} — wybierz państwo`, state.icon);
        d.body.append(make('p', `${sat.name} (poziom ${sat.level || 1}) poleci nad wybrane państwo z prędkością ${sat.speed || state.speeds.mission} km/h Entendy i rozpozna obiekty („${mission.label.toLowerCase()}”) na całym jego terytorium. Satelita szpieguje skutecznie bez względu na ochronę kontrwywiadowczą państwa.`));
        const label = make('label', 'Państwo do rozpoznania'), select = make('select'); select.required = true;
        for (const country of state.countries || []) { const option = make('option', country.name); option.value = country.id; select.append(option); }
        label.append(select); d.body.append(label);
        const quote = make('dl', null, 'satellite-quote');
        const row = (k, v) => { const item = make('div'); item.append(make('dt', k), make('dd', v)); quote.append(item); return item.lastChild; };
        row('Koszt użycia satelity', money(state.missionCost) + ' (budżet służb specjalnych)');
        const time = row('Szacowany czas przelotu', '—');
        d.body.append(quote);
        const estimate = () => {
            const target = (state.countries || []).find(c => String(c.id) === select.value), here = position(sat, gameTime());
            if (!target?.point || !here) { time.textContent = '—'; return; }
            const hours = Math.hypot(target.point[0] - here[0], target.point[1] - here[1]) * state.kmPerUnit / (sat.speed || state.speeds.mission);
            time.textContent = hours.toLocaleString('pl-PL', { maximumFractionDigits: 1 }) + ' godz. Entendy';
        };
        select.onchange = estimate; estimate();
        const cancel = make('button', 'Anuluj', 'satellite-secondary'); cancel.type = 'button'; cancel.onclick = () => d.box.close();
        const confirm = make('button', 'Wyślij satelitę', 'satellite-primary'); confirm.type = 'submit';
        d.actions.append(cancel, confirm);
        d.form.addEventListener('submit', async event => {
            event.preventDefault(); confirm.disabled = true; d.error.textContent = '';
            try {
                const result = await post(state.missionUrl, { request_id: uuid(), satellite_id: sat.id, kind: mission.code, country_id: Number(select.value) }, csrf);
                d.box.close(); notice(result.message); await load();
            } catch (error) { d.error.textContent = error.message; confirm.disabled = false; }
        });
        d.box.showModal(); select.focus();
    }

    // 26 Nov 2026: rozbudowa satelity (szybszy przelot w misji) i anulowanie misji (koszt nie wraca)
    function upgradeDialog(sat, csrf) {
        const next = (sat.level || 1) + 1, rule = state.levels[String(next)];
        const d = dialog(`Rozbudowa: ${sat.name}`, state.upgradeIcon);
        d.body.append(make('p', `Satelita na poziomie ${next} leci nad państwo celu z prędkością ${rule.speed} km/h Entendy (teraz ${sat.speed} km/h). Rozbudowa jest możliwa tylko wtedy, gdy satelita nie wykonuje misji.`));
        const quote = make('dl', null, 'satellite-quote');
        for (const [k, v] of [['Poziom', `${sat.level || 1} → ${next}`], ['Prędkość w misji', `${sat.speed} → ${rule.speed} km/h`], ['Koszt rozbudowy', money(rule.cost) + ' (budżet służb specjalnych)']]) { const item = make('div'); item.append(make('dt', k), make('dd', v)); quote.append(item); }
        d.body.append(quote);
        const cancel = make('button', 'Anuluj', 'satellite-secondary'); cancel.type = 'button'; cancel.onclick = () => d.box.close();
        const confirm = make('button', 'Rozbuduj satelitę', 'satellite-primary'); confirm.type = 'submit';
        d.actions.append(cancel, confirm);
        d.form.addEventListener('submit', async event => {
            event.preventDefault(); confirm.disabled = true; d.error.textContent = '';
            try { const result = await post(state.upgradeUrl, { request_id: uuid(), satellite_id: sat.id, expected_level: sat.level || 1 }, csrf); d.box.close(); notice(result.message); await load(); }
            catch (error) { d.error.textContent = error.message; confirm.disabled = false; }
        });
        d.box.showModal();
    }
    function cancelDialog(sat, csrf) {
        const d = dialog(`Anulować misję? — ${sat.name}`, state.cancelIcon);
        d.box.classList.add('is-danger');
        d.body.append(make('p', sat.mission ? `Misja: ${sat.mission.label} — ${sat.mission.target}.` : 'Satelita leci w misji rozpoznawczej.'),
            make('p', 'Satelita przerwie przelot i wróci do swobodnego dryfu z bieżącego miejsca. Raport nie powstanie, a środki za misję nie są zwracane.'));
        const cancel = make('button', 'Wróć', 'satellite-secondary'); cancel.type = 'button'; cancel.onclick = () => d.box.close();
        const confirm = make('button', 'Anuluj misję', 'satellite-primary satellite-danger'); confirm.type = 'submit';
        d.actions.append(cancel, confirm);
        d.form.addEventListener('submit', async event => {
            event.preventDefault(); confirm.disabled = true; d.error.textContent = '';
            try { const result = await post(state.cancelUrl, { request_id: uuid(), satellite_id: sat.id }, csrf); d.box.close(); notice(result.message); await load(); }
            catch (error) { d.error.textContent = error.message; confirm.disabled = false; }
        });
        d.box.showModal();
    }

    function notice(text) {
        const node = make('div', text, 'satellite-toast'); node.setAttribute('role', 'status'); document.body.append(node);
        setTimeout(() => node.classList.add('is-hiding'), 5000); setTimeout(() => node.remove(), 5600);
    }

    /* Wyniesienie satelity: najpierw rozkaz na serwerze (zużycie satelity, rakiety i ropy), potem minuta paska postępu.
       Okna nie da się zamknąć (Esc, kliknięcie obok) przed końcem — zamyka się samo. */
    async function launch(base, csrf, done) {
        if (!state) { try { await load(); } catch { } }
        const icons = state || { icon: '/static/icons/SATELITA%20SZPIEGOWSKI.svg', flightIcon: '/static/icons/SATELITA%20SZPIEGOWSKI%20LOT.svg', launchUrl: '/game/satelity/wystrzel', launchSeconds: 60 };
        const d = dialog('Wyniesienie satelity na orbitę', icons.launchIcon || icons.icon);
        d.box.classList.add('satellite-launch-dialog');
        d.body.append(make('p', `Satelita szpiegowski wystartuje z bazy: ${base.name || 'baza lotnicza #' + base.id}. Start zużywa 1 satelitę z magazynu, 1 rakietę dalekiego zasięgu i 300 jednostek ropy naftowej.`));
        const cancel = make('button', 'Anuluj', 'satellite-secondary'); cancel.type = 'button'; cancel.onclick = () => d.box.close();
        const confirm = make('button', 'Wynieś satelitę', 'satellite-primary'); confirm.type = 'submit';
        d.actions.append(cancel, confirm);
        let locked = false;
        d.box.addEventListener('cancel', event => { if (locked) event.preventDefault(); });
        d.form.addEventListener('submit', async event => {
            event.preventDefault(); if (locked) return; confirm.disabled = true; d.error.textContent = '';
            let result;
            try { result = await post(icons.launchUrl, { request_id: uuid(), base_id: base.id }, csrf); }
            catch (error) { d.error.textContent = error.message; confirm.disabled = false; return; }
            locked = true; d.actions.replaceChildren(); d.body.replaceChildren();
            const seconds = Number(result.seconds || icons.launchSeconds || 60);
            const label = make('p', 'Trwa wynoszenie satelity w kosmos', 'satellite-progress-label');
            const track = make('div', null, 'satellite-progress'), fill = make('div', null, 'satellite-progress-fill'), rocket = img(icons.flightIcon, 'satellite-progress-icon');
            track.setAttribute('role', 'progressbar'); track.setAttribute('aria-valuemin', '0'); track.setAttribute('aria-valuemax', '100'); track.setAttribute('aria-label', 'Trwa wynoszenie satelity w kosmos');
            fill.append(rocket); track.append(fill);
            const left = make('p', null, 'satellite-progress-left');
            d.body.append(label, track, left);
            const started = performance.now();
            const tick = () => {
                const share = Math.min(1, (performance.now() - started) / (seconds * 1000));
                fill.style.width = (share * 100).toFixed(2) + '%'; track.setAttribute('aria-valuenow', String(Math.round(share * 100)));
                left.textContent = share < 1 ? `Pozostało: ${Math.ceil(seconds * (1 - share))} s` : 'Satelita osiągnął orbitę.';
                if (share < 1) requestAnimationFrame(tick);
                else setTimeout(() => { locked = false; d.box.close(); notice(result.message || 'Satelita jest na orbicie.'); load().catch(() => { }); done?.(); }, 700);
            };
            requestAnimationFrame(tick);
        });
        d.box.showModal();
    }

    // ---------------- warstwa mapy ----------------
    function attach(map, options = {}) {
        if (!window.L || !map) return null;
        const mode = options.mode || 'world';
        const intelEnabled = mode !== 'war';   // w panelu wojennym rozpoznane obiekty są zwykłymi celami (known_ids)
        if (!map.getPane('satelliteIntel')) { map.createPane('satelliteIntel').style.zIndex = '640'; }
        if (!map.getPane('satellites')) { map.createPane('satellites').style.zIndex = '680'; }   // pod kołem opcji (690)
        if (!map.getPane('satelliteTips')) { const tips = map.createPane('satelliteTips'); tips.style.zIndex = '950'; tips.style.pointerEvents = 'none'; }
        const satLayer = L.layerGroup(), intelLayer = L.layerGroup();
        const markers = new Map();
        const view = { render: null };

        function satIcon(sat) {
            const box = make('div', null, 'satellite-marker' + (sat.own ? ' is-own' : '') + (sat.mode === 'mission' ? ' is-mission' : ''));
            box.append(img(state.flightIcon, 'satellite-marker-icon'));
            if (sat.flag) box.append(img(sat.flag, 'satellite-marker-flag'));
            return L.divIcon({ html: box, className: 'satellite-marker-wrap', iconSize: [38, 38], iconAnchor: [19, 19] });
        }
        function satTip(sat) {
            const box = make('div', null, 'satellite-tip');
            const head = make('div', null, 'satellite-tip-head'); head.append(img(state.icon)); const title = make('div'); title.append(make('strong', sat.name), make('span', sat.country)); head.append(title); box.append(head);
            const status = sat.status === 'launching' ? 'Wynoszenie na orbitę' : sat.mission ? `Misja: ${sat.mission.label} — ${sat.mission.target}` : sat.mode === 'mission' ? 'Przelot w misji rozpoznawczej' : `Dryf po orbicie (${state.speeds.drift} km/h)`;
            box.append(make('p', status));
            if (sat.level) box.append(make('p', `Poziom ${sat.level} · przelot w misji ${sat.speed} km/h`));
            if (sat.mission) box.append(make('p', `Dotarcie nad cel: ${when(sat.mission.arrivesAt)} (Entenda)`));
            if (sat.own && mode === 'intelligence' && sat.status === 'orbit') box.append(make('p', sat.mode === 'mission' ? 'Kliknij satelitę, aby anulować misję.' : 'Kliknij satelitę, aby wybrać misję lub go rozbudować.', 'satellite-tip-hint'));
            else if (sat.own && mode !== 'intelligence') box.append(make('p', 'Misje zlecasz na ekranie „Wywiad wojskowy”.', 'satellite-tip-hint'));
            return box;
        }
        function intelIcon(item) {
            const box = make('div', null, 'satellite-intel-marker'); box.append(img(item.icon));
            if (item.flag) box.append(img(item.flag, 'satellite-intel-flag'));
            return L.divIcon({ html: box, className: 'satellite-marker-wrap', iconSize: [28, 28], iconAnchor: [14, 14] });
        }
        function intelTip(item) {
            const box = make('div', null, 'satellite-tip');
            const head = make('div', null, 'satellite-tip-head'); head.append(img(item.icon)); const title = make('div'); title.append(make('strong', item.name), make('span', item.country)); head.append(title); box.append(head);
            box.append(make('p', item.detail || ''), make('p', `Rozpoznanie satelitarne (${item.mission.toLowerCase()}), ${item.observedAt}.`, 'satellite-tip-hint'));
            return box;
        }
        function openMenu(sat, point) {
            if (!window.GameRadialMenu) return;
            const busy = sat.mode === 'mission', top = (sat.level || 1) >= (state.maxLevel || 4);
            const upgrade = { label: top ? `Poziom ${sat.level} (maks.)` : `Rozbuduj do poziomu ${(sat.level || 1) + 1}`, icon: state.upgradeIcon, disabled: busy || top,
                title: top ? 'Satelita ma najwyższy poziom.' : busy ? 'Satelitę można rozbudować tylko wtedy, gdy nie wykonuje misji.' : '', run: () => upgradeDialog(sat, options.csrf) };
            const items = busy ? [{ label: 'Anuluj misję', icon: state.cancelIcon, run: () => cancelDialog(sat, options.csrf) }, upgrade]
                : state.missions.map(mission => ({ label: mission.label, icon: mission.icon, run: () => chooseCountry(sat, mission, options.csrf) })).concat([upgrade]);
            window.GameRadialMenu.open(map, point, items, { key: `satellite:${sat.id}`, label: sat.name, onDisabled: text => notice(text) });
        }
        function render() {
            satLayer.clearLayers(); intelLayer.clearLayers(); markers.clear();
            if (!state?.enabled) return;
            const now = gameTime();
            for (const sat of state.satellites || []) {
                const point = position(sat, now); if (!point) continue;
                const marker = L.marker(latlng(point), { pane: 'satellites', icon: satIcon(sat), keyboard: true, title: sat.name, zIndexOffset: 2000 });
                marker.bindTooltip(() => satTip(sat), { direction: 'top', offset: [0, -18], className: 'satellite-leaflet-tooltip', pane: 'satelliteTips' });
                if (mode === 'intelligence' && sat.own && sat.status === 'orbit') marker.on('click', event => { L.DomEvent.stopPropagation(event); marker.closeTooltip(); openMenu(sat, marker.getLatLng()); });
                marker.addTo(satLayer); markers.set(sat.id, { marker, sat });
            }
            if (intelEnabled) for (const item of state.intel || []) {
                if (!item.position) continue;
                L.marker(latlng(item.position), { pane: 'satelliteIntel', icon: intelIcon(item), keyboard: false })
                    .bindTooltip(() => intelTip(item), { direction: 'top', offset: [0, -12], className: 'satellite-leaflet-tooltip', pane: 'satelliteTips' }).addTo(intelLayer);
            }
            sync();
            options.onRender?.(state);
        }
        function sync() {
            const showSat = filterOn('satellites'), showIntel = showSat && intelEnabled;   // 26 Nov 2026: jeden filtr — satelity i rozpoznane obiekty
            if (showSat && !map.hasLayer(satLayer)) satLayer.addTo(map); else if (!showSat && map.hasLayer(satLayer)) map.removeLayer(satLayer);
            if (showIntel && !map.hasLayer(intelLayer)) intelLayer.addTo(map); else if (!showIntel && map.hasLayer(intelLayer)) map.removeLayer(intelLayer);
            for (const control of filterControls) control.update();
        }
        function animate() {
            if (!state) return;
            const now = gameTime();
            for (const { marker, sat } of markers.values()) {
                const point = position(sat, now); if (!point) continue;
                const next = latlng(point); marker.setLatLng(next); window.GameRadialMenu?.follow?.(`satellite:${sat.id}`, next);
            }
        }
        // Filtry: przyciski w pasku filtrów strony (styl strony) albo kontrolka Leaflet w prawym górnym rogu mapy.
        const filterControls = [];
        const filters = [['satellites', 'Rozpoznanie satelitarne', 'Satelity szpiegowskie na orbicie (własne i — gdy masz satelitę na orbicie — innych państw) oraz obiekty rozpoznane przez Twoje satelity']];
        function addFilter(host, [kind, label, title]) {
            if (options.filterStyle === 'checkbox') {
                const wrap = make('label', null, 'world-layer-toggle satellite-filter'); wrap.title = title; const box = make('input'); box.type = 'checkbox';
                wrap.append(box, make('span', label)); host.append(wrap);
                box.onchange = () => { setFilter(kind, box.checked); sync(); };
                filterControls.push({ update: () => { box.checked = filterOn(kind); } });
            } else {
                const button = make('button', null, options.filterClass || 'satellite-filter-button'); button.type = 'button'; button.title = title;
                button.append(img('/static/icons/SATELITA%20SZPIEGOWSKI%20LOT.svg'), make('span', label));
                host.append(button);
                button.onclick = () => { setFilter(kind, !filterOn(kind)); sync(); };
                filterControls.push({ update: () => { button.setAttribute('aria-pressed', String(filterOn(kind))); } });
            }
        }
        if (options.filterHost) for (const filter of filters) addFilter(options.filterHost, filter);
        else {
            const Control = L.Control.extend({ onAdd() { const host = make('div', null, 'satellite-map-filters leaflet-bar'); L.DomEvent.disableClickPropagation(host); for (const filter of filters) addFilter(host, filter); return host; } });
            new Control({ position: 'topright' }).addTo(map);
        }
        view.render = render;
        views.push(view);
        if (state) render(); else load().catch(() => { });
        setInterval(animate, 1000);
        return { refresh: load, render };
    }

    // ---------------- panel ekranu wywiadu ----------------
    function panel(host) {
        if (!host) return;
        const view = {
            render() {
                host.replaceChildren();
                if (!state?.enabled) { host.append(make('p', 'Satelity szpiegowskie nie są dostępne na tym serwerze.')); return; }
                const own = (state.satellites || []).filter(s => s.own);
                const summary = make('p', null, 'satellite-panel-summary');
                summary.textContent = own.length ? `Twoje satelity na orbicie: ${own.length}. Kliknij satelitę na mapie, aby wybrać misję (koszt ${money(state.missionCost)} z budżetu służb).`
                    : 'Nie masz satelitów na orbicie. Opracuj technologię „Satelita szpiegowski”, wyprodukuj satelitę w fabryce satelitów i wynieś go z bazy lotniczej na ekranie „Obrona państwa”.';
                host.append(summary);
                for (const sat of own) {
                    const card = make('article', null, 'satellite-card'); const head = make('header'); head.append(img(state.icon));
                    const title = make('div'); title.append(make('strong', `${sat.name} · poziom ${sat.level || 1} (${sat.speed || state.speeds.mission} km/h)`), make('span', sat.status === 'launching' ? 'Wynoszenie na orbitę' : sat.mission ? `Misja: ${sat.mission.label} — ${sat.mission.target}` : 'Na orbicie — gotowy do misji'));
                    head.append(title); card.append(head);
                    if (sat.mission) card.append(make('p', `Dotarcie nad cel i raport: ${when(sat.mission.arrivesAt)} (Entenda).`));
                    host.append(card);
                }
                const reports = state.reports || [];
                if (reports.length) {
                    host.append(make('h3', 'Raporty z misji satelitarnych', 'satellite-panel-heading'));
                    for (const report of reports.slice(0, 20)) {
                        const item = make('details', null, 'satellite-report'); const summaryRow = make('summary');
                        summaryRow.append(make('strong', `${report.label} — ${report.country}`), make('span', report.cancelled ? `anulowana ${when(report.endedAt)}` : report.completed ? `zakończona ${when(report.arrivesAt)}` : `w toku, raport ${when(report.arrivesAt)}`));
                        item.append(summaryRow);
                        if (report.completed) { const list = make('dl'); for (const entry of report.entries) { const row = make('div'); row.append(make('dt', entry.label), make('dd', entry.value)); list.append(row); } item.append(list); }
                        else item.append(make('p', 'Satelita leci nad państwo celu.'));
                        host.append(item);
                    }
                }
            }
        };
        views.push(view);
        if (state) view.render();
    }

    setInterval(() => { if (!document.hidden && views.length) load().catch(() => { }); }, 15000);
    window.GameSatellites = { attach, launch, panel, refresh: load, state: () => state };
})();
