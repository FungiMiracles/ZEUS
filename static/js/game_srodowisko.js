"use strict";

(() => {
    const element = document.getElementById("environment-map-config");
    if (!element) return;
    const config = JSON.parse(element.textContent);
    const metropolitanIds = new Set(config.metropolitanRegionIds);
    const status = document.getElementById("environment-map-status");
    function showStatus(message) {
        status.textContent = message;
        status.hidden = false;
    }
    if (!window.L) {
        showStatus("Nie udało się załadować biblioteki mapy. Wartości regionów są dostępne w tabeli poniżej.");
        return;
    }
    const mapElement = document.getElementById("environment-map");
    const map = L.map(mapElement, {
        crs: L.CRS.Simple, minZoom: -10, maxZoom: 8, zoomSnap: 0.25,
        attributionControl: false
    });
    map.setView([0, 0], 0);
    let metric = "air";
    let regionLayer = null;
    let bounds = null;
    const colors = ["#1a9850", "#91cf60", "#fee08b", "#fc8d59", "#d73027"];
    const thresholds = [20, 40, 60, 80];
    const tabs = Array.from(document.querySelectorAll("[data-environment-metric]"));
    function regionStyle(feature) {
        const value = config.regions[String(feature.properties.region_id)][metric];
        const index = thresholds.findIndex(limit => value <= limit);
        return {
            color: "#fff", weight: 1.5, fillOpacity: 0.85,
            fillColor: value == null ? "#cbd5e1" : colors[index === -1 ? 4 : index]
        };
    }
    function tooltip(region) {
        const root = document.createElement("div");
        const title = document.createElement("strong");
        title.textContent = region.name;
        const text = document.createElement("div");
        text.textContent = `${config.metrics[metric]}: ${region[metric] == null ? "brak danych" : region[metric] + " / 100"}`;
        root.append(title, text);
        return root;
    }
    function selectMetric(tab) {
        metric = tab.dataset.environmentMetric;
        tabs.forEach(item => {
            item.setAttribute("aria-selected", String(item === tab));
            item.tabIndex = item === tab ? 0 : -1;
        });
        document.getElementById("environment-map-panel").setAttribute("aria-labelledby", tab.id);
        mapElement.setAttribute("aria-label", `Mapa: ${config.metrics[metric]} w regionach`);
        if (regionLayer) {
            regionLayer.setStyle(regionStyle);
            regionLayer.eachLayer(layer => {
                layer.closeTooltip();
                layer.setTooltipContent(tooltip(config.regions[String(layer.feature.properties.region_id)]));
            });
        }
        map.invalidateSize();
    }
    tabs.forEach((tab, index) => {
        tab.addEventListener("click", () => selectMetric(tab));
        tab.addEventListener("keydown", event => {
            let target;
            if (event.key === "ArrowRight") target = (index + 1) % tabs.length;
            else if (event.key === "ArrowLeft") target = (index - 1 + tabs.length) % tabs.length;
            else if (event.key === "Home") target = 0;
            else if (event.key === "End") target = tabs.length - 1;
            else return;
            event.preventDefault();
            tabs[target].focus();
            selectMetric(tabs[target]);
        });
    });
    const reset = L.DomUtil.create("button", "environment-map-reset");
    reset.type = "button";
    reset.textContent = "Wyśrodkuj państwo";
    reset.disabled = true;
    function focusCountry() {
        if (!bounds || !bounds.isValid()) return;
        map.invalidateSize();
        map.fitBounds(bounds, { padding: [25, 25], maxZoom: 5, animate: false });
    }
    reset.addEventListener("click", focusCountry);
    const control = L.control({ position: "topright" });
    control.onAdd = () => {
        const box = L.DomUtil.create("div", "leaflet-bar");
        box.append(reset);
        L.DomEvent.disableClickPropagation(box);
        L.DomEvent.disableScrollPropagation(box);
        return box;
    };
    control.addTo(map);
    async function load(url) {
        const response = await fetch(url, { credentials: "same-origin" });
        if (!response.ok) throw new Error("Nie udało się pobrać geometrii mapy.");
        const data = await response.json();
        if (!Array.isArray(data.features)) throw new Error("Nieprawidłowa geometria mapy.");
        return data;
    }
    Promise.allSettled([load(config.regionsUrl)]).then(results => {
        const warnings = [];
        const data = results.map((result, index) => {
            if (result.status === "fulfilled") return result.value;
            warnings.push(`Nie udało się wczytać warstwy: regiony.`);
            return { type: "FeatureCollection", features: [] };
        });
        const coordinates = coords => L.latLng(coords[1], coords[0]);
        regionLayer = L.geoJSON(data[0], {
            coordsToLatLng: coordinates,
            filter: feature => metropolitanIds.has(String(feature.properties?.region_id)),
            style: regionStyle,
            onEachFeature: (feature, layer) => {
                const region = config.regions[String(feature.properties.region_id)];
                layer.bindTooltip(tooltip(region), { sticky: true, opacity: 1 });
                layer.on("mouseover", () => layer.setStyle({ color: "#334155", weight: 3 }));
                layer.on("mouseout", () => regionLayer.resetStyle(layer));
            }
        }).addTo(map);
        bounds = regionLayer.getBounds();
        if (bounds.isValid()) {
            reset.disabled = false;
            focusCountry();
        } else warnings.push("Brak geometrii zarządzanego państwa.");
        const mapped = new Set();
        regionLayer.eachLayer(layer => mapped.add(String(layer.feature.properties.region_id)));
        const missing = [...metropolitanIds].filter(id => !mapped.has(id)).length;
        if (missing) warnings.push(`Brak geometrii dla ${missing} regionów. Ich wartości są dostępne w tabeli.`);
        if (warnings.length) showStatus(warnings.join(" "));
    }).catch(() => showStatus("Nie udało się wyświetlić mapy. Wartości regionów są dostępne w tabeli poniżej."));
    if (window.ResizeObserver) {
        new ResizeObserver(() => map.invalidateSize()).observe(mapElement);
    } else window.addEventListener("resize", () => map.invalidateSize());
})();
