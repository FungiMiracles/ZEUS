(() => {
    'use strict';
    const cfg = JSON.parse(document.getElementById('population-config').textContent);
    const form = document.getElementById('population-form');
    const select = document.getElementById('population-country');
    const status = document.getElementById('population-status');
    const save = document.getElementById('population-save');
    const keys = ['children', 'working', 'seniors'];
    const structured = new Set((cfg.structuredCountries || []).map(String));
    let current = null, revision = 0, busy = false, countryLayer = null;
    let automatic = null, edited = [];
    const hundredths = value => /^\d+(?:[.,]\d{1,2})?$/.test(value)
        ? Math.round(Number(value.replace(',', '.')) * 100) : NaN;

    function paintWorld(data) {
        if (!data) return;
        for (const group of data.groups) {
            const percent = group.percent.toLocaleString('pl-PL', {minimumFractionDigits: 2, maximumFractionDigits: 2}) + '%';
            const segment = document.querySelector('[data-world-age="' + group.key + '"]');
            segment.style.width = group.percent + '%';
            segment.title = group.label + ': ' + percent;
            segment.setAttribute('aria-label', segment.title);
            document.querySelector('[data-world-percent="' + group.key + '"]').textContent = percent;
        }
        document.getElementById('population-world-coverage').textContent = data.coveredPopulation === '0'
            ? 'Brak danych o strukturze ludności świata.'
            : 'Udziały ważone liczbą mieszkańców. Zapisane struktury obejmują '
                + data.coveragePercent.toLocaleString('pl-PL', {maximumFractionDigits: 4}) + '% ludności świata.';
    }

    function countryStyle(feature) {
        const id = String(feature.properties.panstwo_id);
        const selected = id === select.value;
        return {color: selected ? '#174c85' : '#71859a', weight: selected ? 2.5 : 1,
            fillColor: selected ? '#4a90d9' : structured.has(id) ? '#70bd92' : '#dce5ee', fillOpacity: .85};
    }
    function paintMap() { if (countryLayer) countryLayer.setStyle(countryStyle); }

    function complete(changed) {
        if (!keys.includes(changed)) return;
        edited = edited.filter(key => key !== changed);
        edited.push(changed);
        // Changing the computed field makes it an entered value again.
        if (automatic === changed) automatic = null;
        const shares = Object.fromEntries(keys.map(key => [key, hundredths(form.elements[key].value)]));
        const valid = key => Number.isFinite(shares[key]) && shares[key] >= 0 && shares[key] <= 10000;
        const blank = keys.filter(key => form.elements[key].value === '');
        let target = automatic;
        if (!target && blank.length === 1) target = blank[0];
        if (!target && edited.length >= 2) target = keys.find(key => !edited.slice(-2).includes(key));
        if (target && target !== changed) {
            const sources = keys.filter(key => key !== target);
            if (sources.every(valid)) {
                const remaining = 10000 - sources.reduce((sum, key) => sum + shares[key], 0);
                if (remaining >= 0 && remaining <= 10000) {
                    form.elements[target].value = (remaining / 100).toFixed(2);
                    automatic = target;
                } else if (automatic === target) {
                    form.elements[target].value = '';
                }
            } else if (automatic === target) {
                form.elements[target].value = '';
            }
        }
        keys.forEach(key => form.elements[key].dataset.automatic = String(key === automatic));
    }

    function update() {
        const shares = keys.map(key => hundredths(form.elements[key].value));
        const sum = shares.reduce((a, b) => a + b, 0);
        const valid = sum === 10000 && shares.every(n => n >= 0 && n <= 10000);
        const sumLabel = document.getElementById('population-sum');
        sumLabel.textContent = 'Suma: ' + (Number.isFinite(sum) ? (sum / 100).toFixed(2) : '—') + '%';
        sumLabel.dataset.valid = String(valid);
        select.disabled = busy;
        keys.forEach(key => form.elements[key].disabled = busy || !current);
        save.disabled = busy || !current || !valid;
        let counts = shares.map(() => null);
        if (current?.population != null && valid) {
            const total = BigInt(current.population), raw = shares.map(n => total * BigInt(n));
            counts = raw.map(n => n / 10000n);
            let rest = total - counts.reduce((a, b) => a + b, 0n);
            for (const i of [0, 1, 2].sort((a, b) => Number(raw[b] % 10000n - raw[a] % 10000n))) {
                if (rest > 0n) { counts[i]++; rest--; }
            }
        }
        keys.forEach((key, i) => form.querySelector('[data-age-count="' + key + '"]').textContent =
            counts[i] === null ? '—' : counts[i].toLocaleString('pl-PL') + ' osób');
    }

    async function load() {
        const token = ++revision;
        current = null; automatic = null; edited = [];
        keys.forEach(key => { form.elements[key].value = ''; form.elements[key].dataset.automatic = 'false'; });
        status.textContent = '';
        document.getElementById('population-total').textContent = 'Wybierz państwo, aby wyświetlić ludność.';
        paintMap(); update();
        if (!select.value) return;
        status.textContent = 'Wczytywanie danych…';
        try {
            const response = await fetch(cfg.stateUrl.replace(/0$/, select.value), {cache: 'no-store'});
            const data = await response.json();
            if (token !== revision) return;
            if (!response.ok) throw Error(data.error);
            current = data;
            if (data.groups.length) structured.add(String(data.countryId));
            else structured.delete(String(data.countryId));
            document.getElementById('population-total').textContent = 'Ludność: ' +
                (data.population == null ? 'brak danych' : BigInt(data.population).toLocaleString('pl-PL'));
            keys.forEach(key => form.elements[key].value = data.groups.find(g => g.key === key)?.percent ?? '');
            status.textContent = data.groups.length ? 'Struktura zapisana. Możesz zmienić udziały.' :
                'Brak zapisanej struktury. Wprowadź dwa udziały.';
            paintMap(); update();
        } catch (error) { if (token === revision) status.textContent = error.message; }
    }
    select.onchange = load;
    form.oninput = event => { complete(event.target.name); update(); };
    form.onsubmit = async event => {
        event.preventDefault();
        if (save.disabled) return;
        busy = true; update();
        try {
            const response = await fetch(cfg.saveUrl, {method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-CSRF-Token': cfg.csrf},
                body: JSON.stringify({country_id: Number(select.value), version: current.version,
                    ...Object.fromEntries(keys.map(key => [key, form.elements[key].value]))})});
            const data = await response.json();
            if (!response.ok) throw Error(data.error);
            current = data;
            structured.add(String(data.countryId)); paintMap();
            paintWorld(data.worldStructure);
            automatic = null; edited = [];
            keys.forEach(key => form.elements[key].dataset.automatic = 'false');
            status.textContent = 'Zapisano strukturę ludności.';
        } catch (error) { status.textContent = error.message; }
        finally { busy = false; update(); }
    };

    if (window.L) {
        const map = L.map('population-map', {crs: L.CRS.Simple, minZoom: -10, maxZoom: 8,
            attributionControl: false}).setView([0, 0], 0);
        fetch(cfg.countriesUrl).then(response => {
            if (!response.ok) throw Error('Mapa niedostępna');
            return response.json();
        }).then(data => {
            countryLayer = L.geoJSON(data, {
                filter: feature => Object.hasOwn(cfg.countries, String(feature.properties.panstwo_id)),
                style: countryStyle,
                onEachFeature: (feature, item) => {
                    const owner = String(feature.properties.panstwo_id);
                    item.bindTooltip(document.createTextNode(cfg.countries[owner]));
                    item.on('click', () => { if (!busy) { select.value = owner; load(); } });
                }
            }).addTo(map);
            if (countryLayer.getBounds().isValid()) map.fitBounds(countryLayer.getBounds());
        }).catch(() => status.textContent = 'Mapa niedostępna — wybierz państwo z listy.');
        if (window.ResizeObserver) new ResizeObserver(() => map.invalidateSize()).observe(document.getElementById('population-map'));
    }
    paintWorld(cfg.worldStructure);
    update();
    if (cfg.countryId) { select.value = cfg.countryId; load(); }
})();
