(() => {
    'use strict';
    const config = JSON.parse(document.getElementById('resource-map-config').textContent);
    const suggest = document.getElementById('suggest-technology');
    suggest?.addEventListener('click', () => { document.getElementById('resources-technology').value = suggest.dataset.value; });
    const resourceSelect = document.getElementById('random-resource');
    const resourceIcon = document.getElementById('random-resource-icon');
    if (resourceSelect && resourceIcon) {
        const updateIcon = () => { resourceIcon.src = resourceSelect.selectedOptions[0].dataset.icon; };
        resourceSelect.addEventListener('change', updateIcon);
        updateIcon();
    }
    const status = document.getElementById('resources-map-status');
    const resourceColors = {
        wegiel_kamienny:'#1b1b1a', ropa_naftowa:'#332e20', zloto:'#f8c809', srebro:'#acaca8', kamien:'#5c5c5a',
        natsyt:'#c94408', kerbit:'#085ec9', cemium:'#c9af08', uran:'#417505', zelazo:'#757980'
    };
    const thresholds = [200n, 500n, 1000n, 10000n];
    const ranges = ['0–200', '201–500', '501–1000', '1001–10 000', '10 001+'];
    const buttons = [...document.querySelectorAll('[data-map-resource]')];
    let activeResource = new URLSearchParams(location.search).get('resource') || '';
    if (!Object.hasOwn(resourceColors, activeResource)) activeResource = '';
    let regionLayer;
    function palette(code) {
        const hex = resourceColors[code];
        const rgb = [1, 3, 5].map(start => parseInt(hex.slice(start, start + 2), 16));
        return [.12, .32, .52, .75, 1].map(strength => 'rgb(' + rgb.map(value => Math.round(255 + (value - 255) * strength)).join(',') + ')');
    }
    function regionStyle(feature) {
        const id = String(feature.properties.region_id), region = config.regions[id];
        const selected = id === config.selected;
        if (activeResource) {
            const quantity = (region?.deposits || []).filter(item => item.code === activeResource)
                .reduce((total, item) => total + BigInt(item.quantity), 0n);
            const index = thresholds.findIndex(limit => quantity <= limit);
            return {color:selected ? '#ad2366' : '#56616b', weight:selected ? 3 : 1,
                fillColor:palette(activeResource)[index < 0 ? 4 : index], fillOpacity:1};
        }
        const hasMinerals = region?.hasMinerals;
        return {color:selected && hasMinerals ? '#f2c94c' : '#244984', weight:selected && hasMinerals ? 3 : 1,
            fillColor:hasMinerals ? '#218838' : (selected ? '#f2c94c' : '#779ce4'), fillOpacity:.5};
    }
    function updateFilter() {
        buttons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.mapResource === activeResource)));
        const legend = document.getElementById('resources-map-legend'); legend.replaceChildren();
        const title = document.createElement('strong');
        title.textContent = activeResource ? buttons.find(button => button.dataset.mapResource === activeResource).textContent.trim() + ' — zasobność regionu' : 'Wszystkie surowce';
        legend.append(title);
        const entries = activeResource ? ranges.map((text, index) => [palette(activeResource)[index], text]) : [['#779ce4','Brak złóż'],['#218838','Zapisane złoża']];
        entries.push([activeResource ? '#ad2366' : '#f2c94c', 'Wybrany region (obrys)']);
        for (const [color, text] of entries) {
            const item = document.createElement('span'), swatch = document.createElement('i');
            swatch.style.backgroundColor = color; item.append(swatch, document.createTextNode(text)); legend.append(item);
        }
        regionLayer?.setStyle(regionStyle);
    }
    buttons.forEach(button => button.addEventListener('click', () => {
        activeResource = button.dataset.mapResource;
        const url = new URL(location.href);
        if (activeResource) url.searchParams.set('resource', activeResource); else url.searchParams.delete('resource');
        history.replaceState(null, '', url); updateFilter();
    }));
    updateFilter();
    function fail() { status.hidden = false; status.textContent = 'Nie udało się wyświetlić mapy. Wybierz region z listy.'; }
    if (!window.L) { fail(); return; }
    const map = L.map('resources-world-map', {crs:L.CRS.Simple, minZoom:-10, maxZoom:8, zoomSnap:0.25, attributionControl:false});
    map.setView([0,0],0);
    const load = async url => { const response = await fetch(url); if (!response.ok) throw new Error('map'); return response.json(); };
    Promise.all([load(config.countriesUrl),load(config.regionsUrl)]).then(([countries,regions]) => {
        const world = L.geoJSON(countries,{interactive:false,style:{color:'#193453',weight:2,fillOpacity:0.2}}).addTo(map);
        regionLayer = L.geoJSON(regions,{
            style: regionStyle,
            onEachFeature: (feature,layer) => {
                const id = String(feature.properties.region_id), region = config.regions[id];
                if (!region) return;
                layer.bindTooltip(() => {
                    const label = document.createElement('div');
                    const title = document.createElement('strong');
                    title.textContent = `${config.countries[region.countryId] || ''} — ${region.name}`;
                    label.append(title);
                    const heading = document.createElement('div'); heading.textContent = 'Zapisane złoża surowców:'; label.append(heading);
                    const format = new Intl.NumberFormat('pl-PL');
                    let deposits = region.deposits || [];
                    if (activeResource) {
                        const selected = deposits.filter(item => item.code === activeResource);
                        deposits = [{name:buttons.find(button => button.dataset.mapResource === activeResource).textContent.trim(),
                            quantity:selected.reduce((total, item) => total + BigInt(item.quantity), 0n).toString(), unit:selected[0]?.unit || ''}];
                    }
                    for (const deposit of deposits) {
                        const row = document.createElement('div');
                        row.className = 'resources-deposit-row';
                        const unit = deposit.unit?.trim();
                        const text = document.createElement('span');
                        text.textContent = `${deposit.name}: ${format.format(BigInt(deposit.quantity))}${unit && unit.toUpperCase() !== 'RU' ? ' ' + unit : ''}`;
                        const iconUrl = config.resourceIcons?.[deposit.name];
                        if (iconUrl) {
                            const icon = document.createElement('img');
                            icon.src = iconUrl; icon.width = 24; icon.height = 24; icon.alt = ''; icon.setAttribute('aria-hidden', 'true');
                            row.append(icon);
                        }
                        row.append(text);
                        label.append(row);
                    }
                    if (!deposits.length) {
                        const empty = document.createElement('div'); empty.textContent = 'Brak złóż surowców.'; label.append(empty);
                    }
                    return label;
                },{sticky:true, className:'resources-deposit-tooltip'});
                layer.on('click', () => { const url = new URL(config.url,location.origin); url.searchParams.set('country_id',region.countryId); url.searchParams.set('region_id',id); if(activeResource)url.searchParams.set('resource',activeResource); location.assign(url); });
            }
        }).addTo(map);
        if (world.getBounds().isValid()) map.fitBounds(world.getBounds(),{padding:[15,15]});
        if (window.ResizeObserver) new ResizeObserver(() => map.invalidateSize()).observe(map.getContainer());
    }).catch(fail);
})();
