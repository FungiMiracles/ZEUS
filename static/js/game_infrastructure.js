(() => {
    'use strict';
    const configElement = document.getElementById('infrastructure-map-config');
    if (!configElement) return;
    const config = JSON.parse(configElement.textContent);
    const reserveSummary=document.getElementById('infrastructure-reserve-summary');
    if(reserveSummary)reserveSummary.textContent=window.GameMoney.format(config.reserve);
    const projectCount=document.getElementById('infrastructure-project-count');
    if(projectCount)projectCount.textContent=Object.values(config.regions).reduce((sum,region)=>sum+Object.keys(region.projects||{}).length,0);
    const metropolitanIds = new Set(config.metropolitanRegionIds);
    const status = document.getElementById('infrastructure-map-status');
    function warn(message) { status.textContent = message; status.hidden = false; }
    const panel = document.getElementById('infrastructure-region-details');
    const selector = document.getElementById('infrastructure-region-select');
    const dialog = document.getElementById('infrastructure-expand-dialog');
    let selected, chosen, levels = 1, maximum = 1;
    const money = value => window.GameMoney.format(value,false);
    function selectRegion(id) {
        selected = id; selector.value = id; panel.replaceChildren();
        const region = config.regions[id];
        if (!region || region.foreign) return;
        const title = document.createElement('h2'); title.textContent = region.name; panel.append(title);
        for (const metric of config.metrics) {
            const item = region.indicators[metric.code], project = region.projects[metric.code];
            const row = document.createElement('div'); row.className = 'infrastructure-detail-row';
            const heading = document.createElement('div'); heading.className = 'infrastructure-detail-heading';
            const label = document.createElement('div'); label.className = 'infrastructure-detail-label';
            const icon = document.createElement('img'); icon.src = metric.icon; icon.alt = ''; icon.width = 28; icon.height = 28;
            const text = document.createElement('span'); text.textContent = `${metric.label}: `;
            const value = document.createElement('strong'); value.textContent = `${item.value ?? '—'} / 100`; value.style.color = item.value == null ? '#849180' : item.value >= 75 ? '#52745b' : item.value >= 40 ? '#947342' : '#aa665a'; text.append(value);
            label.append(icon, text); heading.append(label); row.append(heading);
            const button = document.createElement('button'); button.type = 'button'; button.textContent = 'Rozbuduj'; button.className = 'infrastructure-expand-button';
            const buildIcon = document.createElement('img'); buildIcon.src = config.expandButtonIcon; buildIcon.alt = ''; buildIcon.width = 18; buildIcon.height = 18;
            button.prepend(buildIcon);
            button.disabled = !!project || item.value == null || item.value >= 100 || !region.quotes[metric.code] || (metric.code === 'port' && !region.coastal);
            button.addEventListener('click', () => {
                chosen = metric.code; levels = 1; maximum = 100 - item.value;
                document.getElementById('expand-icon').src = metric.icon;
                document.getElementById('expand-title').textContent = `${region.name} — ${metric.label}`;
                document.getElementById('expand-description').textContent = `Obecny poziom: ${item.value} / 100. Wybierz liczbę dodatkowych poziomów.`;
                document.getElementById('expand-reserve').checked = false;
                document.getElementById('expand-error').textContent = '';
                updateQuote(); dialog.showModal();
            }); heading.append(button);
            if (metric.code === 'port' && !region.coastal) {
                const reason = document.createElement('p'); reason.textContent = 'Region nie jest nadmorski.'; row.append(reason);
            }
            if (project) {
                const progress = document.createElement('progress'); progress.max = 100; progress.value = project.progress;
                progress.setAttribute('aria-label', 'Postęp rozbudowy');
                const text = document.createElement('p'); text.textContent = `Trwa rozbudowa infrastruktury. Planowany koniec: ${project.end} (+${project.levels})`;
                row.append(progress, text);
            }
            panel.append(row);
        }
    }
    window.addEventListener('game:infrastructure-budget',event=>{for(const code of Object.keys(config.funds))config.funds[code]=event.detail.available;if(dialog.open&&chosen)updateQuote();});
    function updateQuote() {
        const quote = config.regions[selected].quotes[chosen];
        document.getElementById('expand-levels').textContent = levels;
        document.getElementById('expand-minus').disabled = levels <= 1;
        document.getElementById('expand-plus').disabled = levels >= maximum;
        document.getElementById('expand-cost').textContent = money(Number(quote.unit) * levels);
        document.getElementById('expand-budget').textContent = money(Number(config.funds[chosen] || 0));
        document.getElementById('expand-reserve-value').textContent = money(Number(config.reserve));
        document.getElementById('expand-time').textContent = `${quote.days * levels} dni Entendy`;
        document.getElementById('expand-target').textContent = `${config.regions[selected].indicators[chosen].value + levels} / 100`;
        document.getElementById('expand-error').textContent = '';
        updateFundingWarning();
    }
    function updateFundingWarning() {
        const cost = Number(config.regions[selected].quotes[chosen].unit) * levels;
        const budget = Number(config.funds[chosen] || 0), reserve = Number(config.reserve);
        const warning = document.getElementById('expand-funding-warning');
        warning.textContent = cost > budget + reserve
            ? 'Budżet infrastruktury i rezerwa budżetowa łącznie nie pokrywają kosztów rozbudowy. Zmniejsz liczbę poziomów.'
            : cost > budget && !document.getElementById('expand-reserve').checked
                ? 'Za mało środków w budżecie infrastruktury. Zaznacz zgodę na użycie rezerwy budżetowej.' : '';
        warning.hidden = !warning.textContent;
    }
    document.getElementById('expand-reserve').addEventListener('change', () => {
        document.getElementById('expand-error').textContent = '';
        updateFundingWarning();
    });
    selector.addEventListener('change', () => selectRegion(selector.value));
    document.getElementById('expand-minus').onclick = () => { levels = Math.max(1, levels - 1); updateQuote(); };
    document.getElementById('expand-plus').onclick = () => { levels = Math.min(maximum, levels + 1); updateQuote(); };
    document.getElementById('expand-cancel').onclick = () => dialog.close();
    document.getElementById('infrastructure-expand-form').onsubmit = async event => {
        event.preventDefault();
        const button = document.getElementById('expand-confirm'); button.disabled = true;
        try {
            const response = await fetch(config.startUrl, {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': config.csrf}, body: JSON.stringify({region_id: Number(selected), metric: chosen, levels, use_reserve: document.getElementById('expand-reserve').checked})});
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || 'Nie udało się zlecić rozbudowy.');
            sessionStorage.setItem('infrastructure-selected', selected); location.reload();
        } catch (error) { document.getElementById('expand-error').textContent = error.message; }
        finally { button.disabled = false; }
    };
    if (Object.values(config.regions).some(region => Object.keys(region.projects||{}).length)) {
        setInterval(() => {
            if (!dialog.open && document.getElementById('infrastructure-regions-panel')?.hidden !== true) {
                if (selected) sessionStorage.setItem('infrastructure-selected', selected);
                location.reload();
            }
        }, 60000);
    }
    const saved = sessionStorage.getItem('infrastructure-selected');
    if (saved && config.regions[saved]) selectRegion(saved);
    if (!window.L) { warn('Nie udało się załadować mapy. Wskaźniki są dostępne w tabeli poniżej.'); return; }
    const element = document.getElementById('infrastructure-map');
    const map = L.map(element, {crs: L.CRS.Simple, minZoom: -10, maxZoom: 8, zoomSnap: 0.25, attributionControl: false});
    map.setView([0, 0], 0);
    let bounds;
    const reset = L.DomUtil.create('button', 'infrastructure-map-reset');
    reset.type = 'button'; reset.textContent = 'Pokaż moje państwo'; reset.disabled = true;
    const focus = () => {
        if (bounds?.isValid()) {
            map.invalidateSize();
            map.fitBounds(bounds, {padding: [100, 65], maxZoom: 5, animate: false});
        }
    };
    reset.addEventListener('click', focus);
    const control = L.control({position: 'topright'});
    control.onAdd = () => {
        const box = L.DomUtil.create('div', 'leaflet-bar'); box.append(reset);
        L.DomEvent.disableClickPropagation(box); L.DomEvent.disableScrollPropagation(box);
        return box;
    };
    control.addTo(map);
    async function load(url) {
        const response = await fetch(url, {credentials: 'same-origin'});
        if (!response.ok) throw new Error('map');
        const data = await response.json();
        if (!Array.isArray(data.features)) throw new Error('geometry');
        return data;
    }
    // Wybierz punkt wewnątrz regionu, także przy wklęsłych granicach i wyspach.
    function constructionAnchor(geometry) {
        const polygons = geometry?.type === 'Polygon' ? [geometry.coordinates]
            : geometry?.type === 'MultiPolygon' ? geometry.coordinates : [];
        let best = null;
        for (const rings of polygons) {
            if (!rings[0]?.length) continue;
            const ys = rings[0].map(point => point[1]);
            const bottom = Math.min(...ys), top = Math.max(...ys);
            for (const fraction of [0.5, 0.25, 0.75]) {
                const y = bottom + (top - bottom) * fraction, intersections = [];
                for (const ring of rings) {
                    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
                        const a = ring[j], b = ring[i];
                        if ((a[1] > y) !== (b[1] > y)) intersections.push(a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1]));
                    }
                }
                intersections.sort((a, b) => a - b);
                for (let i = 0; i + 1 < intersections.length; i += 2) {
                    const width = intersections[i + 1] - intersections[i], score = width * (top - bottom);
                    if (!best || score > best.score) best = {point: [y, (intersections[i] + intersections[i + 1]) / 2], score};
                }
            }
        }
        return best;
    }
    Promise.allSettled([load(config.regionsUrl), load(config.citiesUrl)]).then(results => {
        const warnings = [];
        const [regions, cities] = results.map((result, index) => {
            if (result.status === 'fulfilled') return result.value;
            warnings.push(`Nie udało się wczytać warstwy ${['regionów', 'miast'][index]}.`);
            return {type: 'FeatureCollection', features: []};
        });
        const anchors = new Map();
        const constructionAnchors = new Map();
        const regionsLayer = L.geoJSON(regions, {
            coordsToLatLng: coords => L.latLng(coords[1], coords[0]),
            filter: feature => !!config.regions[String(feature.properties?.region_id)] || !!config.foreignRegions?.[String(feature.properties?.region_id)],
            // 13 Nov 2026: paleta mapy panelu państwa (regiony #B8C9B0, granice #667C63, najechany #D5E5C6, wybrany #E8B65C)
            style: feature => ({color: '#667C63', weight: 1.5, fillColor: config.foreignRegions?.[String(feature.properties.region_id)]?.permit ? '#65b96e' : '#B8C9B0', fillOpacity: 1}),
            onEachFeature: (feature, layer) => {
                const id = String(feature.properties.region_id);
                const label = document.createElement('span'); label.textContent = (config.regions[id]||config.foreignRegions[id]).name;
                const foreign=config.foreignRegions?.[id];
                if(foreign){
                    const box=document.createElement('div');box.append(label);
                    for(const entry of foreign.report){const row=document.createElement('p');row.textContent=entry.label+': '+entry.value;box.append(row);}
                    if(!foreign.report.length){const row=document.createElement('p');row.textContent='Brak danych wywiadowczych o zasobach.';box.append(row);}
                    if(foreign.canRequest){const button=document.createElement('button');button.textContent='Wnioskuj o możliwość wydobycia';button.onclick=async event=>{event.stopPropagation();button.disabled=true;try{const response=await fetch('/game/dyplomacja/akcje',{method:'POST',body:new URLSearchParams({kind:'MINING_PERMIT',target_id:foreign.countryId,region_id:id,csrf_token:config.csrf})});const data=await response.json();if(!response.ok)throw Error(data.error||'Nie udało się wysłać wniosku.');button.textContent='Wniosek wysłany';}catch(error){button.disabled=false;warn(error.message);}};box.append(button);}
                    window.GameRegionTooltip.bind(layer,box);
                }else layer.bindTooltip(label, {sticky: true});
                if(!config.regions[id])return;
                anchors.set(id, true);
                if (Object.keys(config.regions[id].projects).length) {
                    const anchor = constructionAnchor(feature.geometry);
                    if (anchor && (!constructionAnchors.has(id) || anchor.score > constructionAnchors.get(id).score)) constructionAnchors.set(id, anchor);
                }
                layer.on({
                    click: () => {
                        if (window.__infraSelected && window.__infraSelected !== layer) regionsLayer.resetStyle(window.__infraSelected);
                        window.__infraSelected = layer; layer.setStyle({fillColor: '#E8B65C', weight: 2.4});
                        selectRegion(id);
                    },
                    mouseover: () => { if (window.__infraSelected !== layer) layer.setStyle({fillColor: '#D5E5C6', weight: 2.2}); },
                    mouseout: () => { if (window.__infraSelected !== layer) regionsLayer.resetStyle(layer); }
                });
            }
        }).addTo(map);
        map.createPane('infrastructureCities');
        map.getPane('infrastructureCities').style.zIndex = '450';
        L.geoJSON(cities, {
            coordsToLatLng: coords => L.latLng(coords[1], coords[0]),
            filter: feature => metropolitanIds.has(config.cities[String(feature.properties?.miasto_id)]?.regionId),
            pointToLayer: (feature, latlng) => L.circleMarker(latlng, {
                pane: 'infrastructureCities', radius: 4.5, color: '#22301f', weight: 1.6,
                fillColor: '#FFFFFF', fillOpacity: 1
            }),
            onEachFeature: (feature, layer) => {
                const city = config.cities[String(feature.properties.miasto_id)];
                const name = document.createElement('span'); name.textContent = city.name;
                layer.bindTooltip(name, {direction: 'top'});
                layer.on('click', () => { if (config.regions[city.regionId]) selectRegion(city.regionId); });
            }
        }).addTo(map);
        for (const [id, anchor] of constructionAnchors) {
            const description = `${config.regions[id].name} — trwają prace budowlane`;
            const tooltip = document.createElement('div'); tooltip.className = 'infrastructure-construction-tooltip';
            for (const metric of config.metrics) {
                const project = config.regions[id].projects[metric.code];
                if (!project) continue;
                const row = document.createElement('div'); row.className = 'infrastructure-construction-tooltip-row';
                const building = document.createElement('img'); building.src = config.constructionIcon; building.alt = 'Prace budowlane';
                const infrastructure = document.createElement('img'); infrastructure.src = metric.icon; infrastructure.alt = metric.label; infrastructure.title = metric.label;
                const progress = document.createElement('span'); progress.textContent = `Ukończono: ${project.progress}%`;
                row.append(building, infrastructure, progress); tooltip.append(row);
            }
            L.marker(anchor.point, {
                icon: L.icon({iconUrl: config.constructionIcon, iconSize: [36, 36], iconAnchor: [18, 18], className: 'infrastructure-construction-marker'}),
                title: description, alt: description, riseOnHover: true
            }).bindTooltip(tooltip,{className:'infrastructure-construction-leaflet-tooltip'}).on('click', () => selectRegion(id)).addTo(map);
        }
        bounds = regionsLayer.getBounds();
        if (bounds.isValid()) { reset.disabled = false; focus(); }
        else warnings.push('Brak geometrii zarządzanego państwa.');
        const missing = [...metropolitanIds].filter(id => !anchors.has(id)).length;
        if (missing) warnings.push(`Brak geometrii dla ${missing} regionów. Ich wskaźniki znajdziesz w tabeli.`);
        if (warnings.length) warn(warnings.join(' '));
    }).catch(() => warn('Nie udało się wyświetlić mapy. Wskaźniki są dostępne w tabeli poniżej.'));
    if (window.ResizeObserver) new ResizeObserver(() => map.invalidateSize()).observe(element);
    else window.addEventListener('resize', () => map.invalidateSize());
})();
