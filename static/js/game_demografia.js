"use strict";

(() => {
    const configElement = document.getElementById("demography-map-config");
    if (!configElement) return;

    const config = JSON.parse(configElement.textContent);
    const metropolitanIds = new Set(config.metropolitanRegionIds);
    const status = document.getElementById("demography-map-status");
    const number = new Intl.NumberFormat("pl-PL");

    function showStatus(message) {
        status.textContent = message;
        status.hidden = false;
    }

    if (!window.L) {
        showStatus("Nie udało się załadować biblioteki mapy.");
        return;
    }

    const map = L.map("demography-map", {
        crs: L.CRS.Simple,
        minZoom: -10,
        maxZoom: 8,
        zoomSnap: 0.25,
        attributionControl: false
    });

    const resetButton = L.DomUtil.create("button", "demo-map-reset");
    resetButton.type = "button";
    resetButton.id = "demography-map-reset";
    resetButton.textContent = "Wyśrodkuj państwo";
    resetButton.disabled = true;
    resetButton.setAttribute("aria-label", "Wyśrodkuj mapę na zarządzanym państwie");

    const resetControl = L.control({ position: "topright" });
    resetControl.onAdd = () => {
        const container = L.DomUtil.create("div", "leaflet-bar demo-map-control");
        container.append(resetButton);
        L.DomEvent.disableClickPropagation(container);
        L.DomEvent.disableScrollPropagation(container);
        return container;
    };
    resetControl.addTo(map);

    const coordinates = coords => L.latLng(coords[1], coords[0]);

    const regionPalette = [
        "#fff7bc", "#fec44f", "#fe9929", "#ec7014", "#b30000"
    ];
    const unknownColor = "#cbd5e1";
    const thresholds = [200_000, 500_000, 1_000_000, 10_000_000];

    function regionColor(population) {
        if (population == null) return unknownColor;
        const index = thresholds.findIndex(limit => population <= limit);
        return regionPalette[index === -1 ? 4 : index];
    }

    function cityRadius(population) {
        if (population == null) return 3;
        if (population <= 200_000) return 4;
        if (population <= 500_000) return 6;
        if (population <= 1_000_000) return 8;
        if (population <= 10_000_000) return 11;
        return 15;
    }

    function bindPopulationTooltip(layer, name, population) {
        const tooltip = document.createElement("div");
        const title = document.createElement("strong");
        const text = document.createElement("div");

        title.textContent = name;
        text.textContent = population == null
            ? "Ludność: brak danych"
            : `Ludność: ${number.format(population)}`;

        tooltip.append(title, text);
        layer.bindTooltip(tooltip, {
            sticky: true,
            direction: "auto",
            opacity: 1
        });
    }

    async function loadGeoJSON(url) {
        const response = await fetch(url, {
            credentials: "same-origin"
        });
        if (!response.ok) {
            throw new Error(`Nie udało się pobrać mapy (${response.status}).`);
        }
        return response.json();
    }

    const legend = document.getElementById("demography-region-legend");
    [
        ["do 200 tys.", regionPalette[0]],
        ["ponad 200–500 tys.", regionPalette[1]],
        ["ponad 500 tys.–1 mln", regionPalette[2]],
        ["ponad 1–10 mln", regionPalette[3]],
        ["ponad 10 mln", regionPalette[4]],
        ["brak danych", unknownColor]
    ].forEach(([label, color]) => {
        const item = document.createElement("span");
        const swatch = document.createElement("i");
        swatch.style.backgroundColor = color;
        item.append(swatch, document.createTextNode(label));
        legend.append(item);
    });

    // Błąd warstwy miast nie blokuje wyświetlenia regionów.
    Promise.allSettled([
        loadGeoJSON(config.regionsUrl),
        loadGeoJSON(config.citiesUrl)
    ]).then(results => {
        const warnings = [];

        function fulfilled(index, label) {
            const result = results[index];
            if (result.status === "fulfilled") return result.value;
            warnings.push(`Nie udało się wczytać warstwy: ${label}.`);
            return { type: "FeatureCollection", features: [] };
        }

        const regions = fulfilled(0, "regiony");
        const cities = fulfilled(1, "miasta");


        const regionLayer = L.geoJSON(regions, {
            coordsToLatLng: coordinates,
            filter: feature => metropolitanIds.has(String(feature.properties?.region_id)),
            style: feature => {
                const region = config.regions[
                    String(feature.properties.region_id)
                ];
                return {
                    color: "#ffffff",
                    weight: 1.5,
                    fillColor: regionColor(region?.population),
                    fillOpacity: 0.85
                };
            },
            onEachFeature: (feature, layer) => {
                const region = config.regions[
                    String(feature.properties.region_id)
                ];

                bindPopulationTooltip(
                    layer,
                    region.name,
                    region.population
                );

                layer.on("mouseover", () => {
                    layer.setStyle({
                        weight: 3,
                        color: "#334155",
                        fillOpacity: 1
                    });
                });
                layer.on("mouseout", () => regionLayer.resetStyle(layer));
            }
        }).addTo(map);

        map.createPane("demographyCities");
        map.getPane("demographyCities").style.zIndex = "450";

        const cityLayer = L.geoJSON(cities, {
            coordsToLatLng: coordinates,
            filter: feature => metropolitanIds.has(config.cities[String(feature.properties?.miasto_id)]?.regionId),
            pointToLayer: (feature, latlng) => {
                const city = config.cities[
                    String(feature.properties.miasto_id)
                ];

                return L.circleMarker(latlng, {
                    pane: "demographyCities",
                    radius: cityRadius(city.population),
                    color: "#ffffff",
                    weight: 1.5,
                    fillColor: "#173b75",
                    fillOpacity: 0.9
                });
            },
            onEachFeature: (feature, layer) => {
                const city = config.cities[
                    String(feature.properties.miasto_id)
                ];
                bindPopulationTooltip(layer, city.name, city.population);
            }
        }).addTo(map);

        const bounds = regionLayer.getBounds();

        function focusCountry() {
            if (!bounds.isValid()) return;

            map.invalidateSize();
            map.fitBounds(bounds, {
                padding: [25, 25],
                maxZoom: 5,
                animate: false
            });
        }

        if (bounds.isValid()) {
            focusCountry();
            resetButton.disabled = false;
            resetButton.addEventListener("click", focusCountry);
        } else {
            map.setView([0, 0], 0);
            warnings.push("Brak geometrii zarządzanego państwa.");
        }

        if (warnings.length) showStatus(warnings.join(" "));

        const observer = new ResizeObserver(() => map.invalidateSize());
        observer.observe(document.getElementById("demography-map"));
        map.invalidateSize();
    }).catch(error => {
        showStatus(error.message || "Nie udało się wyświetlić mapy.");
    });
})();