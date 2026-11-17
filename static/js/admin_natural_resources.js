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
    function fail() { status.hidden = false; status.textContent = 'Nie udało się wyświetlić mapy. Wybierz region z listy.'; }
    if (!window.L) { fail(); return; }
    const map = L.map('resources-world-map', {crs:L.CRS.Simple, minZoom:-10, maxZoom:8, zoomSnap:0.25, attributionControl:false});
    map.setView([0,0],0);
    const load = async url => { const response = await fetch(url); if (!response.ok) throw new Error('map'); return response.json(); };
    Promise.all([load(config.countriesUrl),load(config.regionsUrl)]).then(([countries,regions]) => {
        const world = L.geoJSON(countries,{interactive:false,style:{color:'#193453',weight:2,fillOpacity:0.2}}).addTo(map);
        L.geoJSON(regions,{
            style: f => {
                const id = String(f.properties.region_id);
                const selected = id === config.selected;
                const hasMinerals = config.regions[id]?.hasMinerals;
                return {
                    color: selected && hasMinerals ? '#f2c94c' : '#244984',
                    weight: selected && hasMinerals ? 3 : 1,
                    fillColor: hasMinerals ? '#218838' : (selected ? '#f2c94c' : '#779ce4'),
                    fillOpacity: 0.5
                };
            },
            onEachFeature: (feature,layer) => {
                const id = String(feature.properties.region_id), region = config.regions[id];
                if (!region) return;
                const label = document.createElement('div');
                const title = document.createElement('strong');
                title.textContent = `${config.countries[region.countryId] || ''} — ${region.name}`;
                label.append(title);
                const heading = document.createElement('div'); heading.textContent = 'Zapisane złoża surowców:'; label.append(heading);
                const format = new Intl.NumberFormat('pl-PL');
                for (const deposit of region.deposits || []) {
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
                if (!region.deposits?.length) {
                    const empty = document.createElement('div'); empty.textContent = 'Brak złóż surowców.'; label.append(empty);
                }
                layer.bindTooltip(label,{sticky:true, className:'resources-deposit-tooltip'});
                layer.on('click', () => { const url = new URL(config.url,location.origin); url.searchParams.set('country_id',region.countryId); url.searchParams.set('region_id',id); location.assign(url); });
            }
        }).addTo(map);
        if (world.getBounds().isValid()) map.fitBounds(world.getBounds(),{padding:[15,15]});
        if (window.ResizeObserver) new ResizeObserver(() => map.invalidateSize()).observe(map.getContainer());
    }).catch(fail);
})();
