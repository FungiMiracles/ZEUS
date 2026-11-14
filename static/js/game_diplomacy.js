"use strict";

(() => {
    const element = document.getElementById("diplomacy-map-config");
    if (!element) return;
    const config = JSON.parse(element.textContent);
    const chooser = document.getElementById("diplomacy-country");
    const form = document.getElementById("diplomacy-form");
    const kind = document.getElementById("diplomacy-kind");
    const relation = document.getElementById("diplomacy-relation");
    const result = document.getElementById("diplomacy-result");
    const actionDialog = document.getElementById("diplomacy-actions-dialog");
    document.getElementById("diplomacy-actions-close").addEventListener("click", () => actionDialog.close());
    function openActions() { if (!actionDialog.open) actionDialog.showModal(); }
    const selection = document.getElementById("diplomacy-selection");
    function isBreak() { return kind.value === "RELATION" && config.relationRanks[relation.value] < config.relationRanks[config.countries[chooser.value]?.relationId]; }
    function updateAction() {
        document.getElementById("diplomacy-relation-field").hidden = kind.value !== "RELATION";
        document.getElementById("diplomacy-enemy-field").hidden = kind.value !== "JOIN_WAR";
        document.getElementById("diplomacy-action-help").textContent = kind.value === "WAR"
            ? "Wypowiedzenie wojny działa natychmiast i nie wymaga zgody drugiego gracza."
            : kind.value === "JOIN_WAR" ? "Sojusznik zdecyduje, czy dołączy do wybranej wojny. Zgoda oznacza jego natychmiastowy stan wojny z tym państwem."
            : isBreak() ? "Jednostronne pogorszenie relacji. Wybrana relacja zacznie obowiązywać natychmiast, bez zgody drugiej strony." : "Ta propozycja wymaga akceptacji drugiej strony.";
        form.querySelector('button[type="submit"]').textContent = isBreak() ? "Pogorsz relacje" : "Wyślij";
    }
    function choose(id) {
        chooser.value = id;
        const country = config.countries[id];
        form.hidden = !country || !country.canAct;
        if (!country) { selection.textContent = ""; return; }
        selection.textContent = `${country.name}: ${country.relation} · ${country.state}` +
            (!country.canAct ? " — działania niedostępne: własne państwo lub brak aktywnego gracza lub autonomii." : "");
        document.getElementById("diplomacy-target").value = id;
        const enemy = document.getElementById("diplomacy-enemy");
        enemy.replaceChildren(...(country.joinWars || []).map(war => { const option = document.createElement("option"); option.value = war.id; option.textContent = war.name; return option; }));
        Array.from(kind.options).forEach(option => {
            option.disabled = option.value === "JOIN_WAR" ? !(country.joinWars || []).length : option.value === "WAR" ? !country.canWar
                : ["PEACE", "CEASEFIRE"].includes(option.value) ? !country.canNegotiate || !country.canPropose : !country.canPropose && !country.canWorsen;
            option.hidden = option.disabled;
        });
        kind.value = country.canPropose || country.canWorsen ? "RELATION" : "WAR";
        Array.from(relation.options).forEach(option => { option.disabled = Number(option.value) === country.relationId || (!country.canPropose && config.relationRanks[option.value] >= config.relationRanks[country.relationId]); });
        const available = Array.from(relation.options).find(option => !option.disabled);
        if (available) relation.value = available.value;
        updateAction();
    }
    chooser.addEventListener("change", () => { choose(chooser.value); if (chooser.value) openActions(); });
    kind.addEventListener("change", updateAction);
    relation.addEventListener("change", updateAction);
    form.addEventListener("submit", async event => {
        event.preventDefault();
        if (isBreak() && !window.confirm("Czy na pewno chcesz jednostronnie pogorszyć relacje? Relacja zmieni się natychmiast.")) return;
        if (kind.value === "WAR" && !window.confirm("Czy na pewno wypowiedzieć wojnę temu państwu? Zmiana nastąpi natychmiast.")) return;
        const button = form.querySelector('button[type="submit"]');
        button.disabled = true;
        result.textContent = "Zapisywanie…";
        try {
            const response = await fetch(form.action, { method: "POST", credentials: "same-origin", body: new FormData(form), headers: { Accept: "application/json" } });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || "Nie udało się wykonać działania.");
            result.textContent = data.message;
            window.location.reload();
        } catch (error) { result.textContent = error.message || "Nie udało się wykonać działania."; }
        finally { button.disabled = false; }
    });
    window.addEventListener("game:diplomacy-changed", () => window.location.reload());

    const status = document.getElementById("diplomacy-map-status");
    function warn(message) { status.hidden = false; status.textContent = message; }
    if (!window.L) { warn("Nie udało się załadować mapy. Państwo możesz wybrać z listy poniżej."); return; }
    const map = L.map("diplomacy-map", { crs: L.CRS.Simple, minZoom: -10, maxZoom: 8, zoomSnap: 0.25, attributionControl: false });
    map.setView([0, 0], 0);
    const mapElement = document.getElementById("diplomacy-map");
    let popupCloseTimer;
    function keepPopupOpen() {
        clearTimeout(popupCloseTimer);
    }
    function closeMapPopup() {
        keepPopupOpen();
        map.closePopup();
    }
    function schedulePopupClose() {
        keepPopupOpen();
        popupCloseTimer = setTimeout(() => {
            const focused = document.activeElement;
            if (!focused?.closest(".diplomacy-map-popup")) map.closePopup();
        }, 180);
    }
    // A short bridge lets the pointer move from a country onto its action buttons.
    mapElement.addEventListener("mouseleave", closeMapPopup);
    mapElement.addEventListener("keydown", event => {
        if (event.key === "Escape") closeMapPopup();
    });
    map.on("popupopen", event => {
        keepPopupOpen();
        const popupElement = event.popup.getElement();
        if (!popupElement || popupElement.dataset.diplomacyHoverBound) return;
        popupElement.dataset.diplomacyHoverBound = "true";
        popupElement.addEventListener("mouseenter", keepPopupOpen);
        popupElement.addEventListener("mouseleave", schedulePopupClose);
        popupElement.addEventListener("focusin", keepPopupOpen);
        popupElement.addEventListener("focusout", event => {
            if (!popupElement.contains(event.relatedTarget)) schedulePopupClose();
        });
    });
    map.on("popupclose", keepPopupOpen);
    map.on("movestart zoomstart", closeMapPopup);
    let worldBounds;
    // 13 Nov 2026: przycisk „Cały świat” w granatowym pasku mapy (jak na ekranie Świat).
    const reset = document.getElementById("diplomacy-map-reset");
    reset.disabled = true;
    function focusWorld() {
        if (worldBounds?.isValid()) map.fitBounds(worldBounds, { padding: [20, 20], maxZoom: 3, animate: false });
    }
    reset.addEventListener("click", focusWorld);
    function countryData(feature) { return config.countries[String(feature.properties?.panstwo_id)]; }
    function popup(feature) {
        const country = countryData(feature);
        const box = document.createElement("div");
        if (!country) { box.textContent = "Brak danych państwa."; return box; }
        box.className = "diplomacy-country-popup";
        const heading = document.createElement("div");
        heading.className = "diplomacy-popup-heading";
        const flag = document.createElement("img");
        flag.src = country.flag;
        flag.alt = "Flaga państwa " + country.name;
        const title = document.createElement("strong");
        title.textContent = country.name;
        heading.append(flag, title);
        const text = document.createElement("p");
        text.textContent = `${country.relation} · ${country.state}`;
        box.append(heading, text);
        if(country.pagaConfigured){const note=document.createElement("small");note.textContent="Skonfigurowano w PAGA";box.append(note);}
        if (!country.canAct) {
            const note = document.createElement("p");
            note.textContent = country.own ? "Twoje państwo." : "Brak aktywnego gracza lub autonomii — działania niedostępne.";
            box.append(note);
            return box;
        }
        const options = country.canPropose || country.canWorsen ? [["RELATION", "Zmień relację"]] : [];
        if (country.canWar) options.push(["WAR", "Wypowiedz wojnę"]);
        if (country.canNegotiate && country.canPropose) options.push(["PEACE", "Zaproponuj pokój"], ["CEASEFIRE", "Zaproponuj zawieszenie broni"]);
        if ((country.joinWars || []).length) options.push(["JOIN_WAR", "Poproś o dołączenie do wojny"]);
        options.forEach(([value, label]) => {
            const line = document.createElement("p");
            const button = document.createElement("button");
            button.type = "button";
            button.textContent = label;
            button.className = "diplomacy-action-button action-" + value.toLowerCase();
            button.addEventListener("click", () => {
                choose(String(feature.properties.panstwo_id));
                kind.value = value;
                updateAction();
                map.closePopup();
                openActions();
                kind.focus();
            });
            line.append(button);
            box.append(line);
        });
        return box;
    }
    fetch(config.countriesUrl, { credentials: "same-origin" }).then(response => {
        if (!response.ok) throw new Error();
        return response.json();
    }).then(data => {
        let layer;
        layer = L.geoJSON(data, {
            coordsToLatLng: coords => L.latLng(coords[1], coords[0]),
            // 13 Nov 2026: granice i krycie jak na mapie „Świat”; wypełnienie = relacja z danym państwem.
            style: feature => {
                const country = countryData(feature);
                return { fillColor: country?.color || "#B8C9B0", fillOpacity: 1,
                         color: country?.war ? "#b3261e" : country?.own ? "#1E3A5F" : "#667C63",
                         weight: country?.war ? 3 : country?.own ? 2.5 : 1.4 };
            },
            onEachFeature: (feature, polygon) => {
                polygon.bindPopup(() => popup(feature), {
                    className: "diplomacy-map-popup", minWidth: 180, maxWidth: 260,
                    autoPan: false, closeButton: true
                });
                polygon.on("mouseover", event => {
                    keepPopupOpen();
                    polygon.setStyle({ fillOpacity: 0.72, weight: (countryData(feature)?.war ? 3 : 2.2) });
                    polygon.bringToFront();
                    polygon.openPopup(event.latlng);
                });
                polygon.on("mouseout", () => { layer.resetStyle(polygon); schedulePopupClose(); });
                polygon.on("click", () => choose(String(feature.properties?.panstwo_id)));
            }
        }).addTo(map);
        worldBounds = layer.getBounds();
        if (worldBounds.isValid()) { reset.disabled = false; focusWorld(); }
        else warn("Brak geometrii mapy świata. Wybierz państwo z listy.");
    }).catch(() => warn("Nie udało się pobrać mapy. Państwo możesz wybrać z listy poniżej."));
    if (window.ResizeObserver) new ResizeObserver(() => map.invalidateSize()).observe(document.getElementById("diplomacy-map"));
})();
