/* Read-only road overlay for the WIKI world map (CRS.Simple, stored [x,y]). */
window.addWorldRoadsOverlay = function (map, url) {
    'use strict';
    const toggle = document.getElementById('toggleRoads');
    if (!toggle) return;
    const status = document.getElementById('worldRoadsStatus');
    const legend = document.getElementById('worldRoadsLegend');
    map.createPane('worldRoads');
    map.getPane('worldRoads').style.zIndex = '450';
    const roads = L.geoJSON(null, {
        pane: 'worldRoads',
        style: feature => ({
            color: feature.properties.kind === 'motorway' ? '#ec8b24' : '#e6bf25',
            weight: feature.properties.kind === 'motorway' ? 5 : 3,
            opacity: 1,
            bubblingMouseEvents: false,
        }),
        onEachFeature: (feature, layer) => {
            const p = feature.properties;
            const label = document.createElement('span');
            const kind = p.kind === 'motorway' ? 'Autostrada' : 'Droga krajowa';
            label.textContent = `${kind} #${p.id} · ${p.distanceKm} km · ${p.country}`;
            layer.bindTooltip(label, {sticky: true});
        },
    });
    let pending = null;
    toggle.addEventListener('change', async () => {
        legend.hidden = !toggle.checked;
        if (!toggle.checked) {
            map.removeLayer(roads);
            status.textContent = '';
            return;
        }
        status.textContent = 'Wczytywanie dróg…';
        try {
            // Share an in-flight request across rapid toggles; refresh on later enables.
            if (!pending) pending = fetch(url, {cache: 'no-store', credentials: 'same-origin'})
                .then(response => {
                    if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) {
                        throw new Error('roads');
                    }
                    return response.json();
                }).finally(() => { pending = null; });
            const data = await pending;
            if (!toggle.checked) return;
            roads.clearLayers();
            roads.addData(data);
            roads.addTo(map);
            status.textContent = data.features.length ? '' : 'Brak dróg do wyświetlenia.';
        } catch (error) {
            if (!toggle.checked) return;
            toggle.checked = false;
            legend.hidden = true;
            map.removeLayer(roads);
            status.textContent = 'Nie udało się wczytać dróg. Włącz nakładkę ponownie, aby spróbować jeszcze raz.';
        }
    });
};
