"use strict";

(() => {
    const root = document.getElementById("game-notifications");
    if (!root) return;
    const badge = document.getElementById("game-notification-count");
    const toggle = document.getElementById("game-notifications-toggle");
    const list = document.getElementById("game-notification-list");
    const status = document.getElementById("game-notification-status");
    const more = document.getElementById("game-notification-more");
    let nextPage = null;
    let busy = false;
    const displayed = new Set();

    const dialog = document.getElementById("game-diplomacy-dialog");
    const accept = document.getElementById("game-diplomacy-accept");
    const reject = document.getElementById("game-diplomacy-reject");
    const dialogStatus = document.getElementById("game-diplomacy-status");
    let decisionUrl = null;
    let deciding = false;
    document.getElementById("game-diplomacy-close").addEventListener("click", () => dialog.close());
    function showDiplomacy(data) {
        decisionUrl = data.decision_url;
        document.getElementById("game-diplomacy-title").textContent = data.title;
        document.getElementById("game-diplomacy-text").textContent = data.text;
        document.getElementById("game-diplomacy-relation").textContent = data.relation ? "Proponowana relacja: " + data.relation : "";
        document.getElementById("game-diplomacy-date").textContent = data.received_at + " (Polska)";
        dialogStatus.textContent = data.status;
        accept.hidden = reject.hidden = !data.can_decide;
        accept.disabled = reject.disabled = false;
        root.open = false;
        dialog.showModal();
    }
    async function decide(value) {
        if (deciding || !decisionUrl) return;
        deciding = true;
        accept.disabled = reject.disabled = true;
        const body = new FormData();
        body.set("csrf_token", root.dataset.csrf);
        body.set("decision", value);
        try {
            const response = await fetch(decisionUrl, { method: "POST", credentials: "same-origin", body, headers: { Accept: "application/json" } });
            const data = await response.json();
            if (!response.ok) {
                if (response.status === 409) accept.hidden = reject.hidden = true;
                throw new Error(data.error || "Nie udało się zapisać decyzji.");
            }
            dialogStatus.textContent = data.message;
            accept.hidden = reject.hidden = true;
            window.dispatchEvent(new Event("game:diplomacy-changed"));
            load();
        } catch (error) { dialogStatus.textContent = error.message || "Nie udało się zapisać decyzji."; }
        finally { deciding = false; accept.disabled = reject.disabled = false; }
    }
    accept.addEventListener("click", () => decide("accept"));
    reject.addEventListener("click", () => decide("reject"));

    const eventDialog = document.getElementById("game-event-dialog");
    document.getElementById("game-event-close").addEventListener("click", () => eventDialog.close());
    function appendEffects(container, effects) {
        effects.forEach(effect => {
            const badge = document.createElement("span");
            badge.className = "game-event-effect " + (effect.value >= 0 ? "positive" : "negative");
            badge.textContent = effect.label + " " + (effect.value > 0 ? "+" : "") + effect.value + (effect.suffix || "");
            container.append(badge);
        });
    }
    function showEvent(data) {
        document.getElementById("game-event-title").textContent = data.title;
        document.getElementById("game-event-content").textContent = data.content;
        document.getElementById("game-event-date").textContent = data.country + " · Entenda: " + data.entenda_date + " · " + data.received_at + " (Polska)";
        const effects = document.getElementById("game-event-effects");
        effects.replaceChildren();
        appendEffects(effects, data.effects);
        if (!data.effects.length) effects.textContent = "Brak zarejestrowanych zmian wskaźników.";
        root.open = false;
        eventDialog.showModal();
    }

    const intelligenceDialog=document.getElementById('game-intelligence-dialog');
    document.getElementById('game-intelligence-close').addEventListener('click',()=>intelligenceDialog.close());
    window.showIntelligenceReport=data=>{
        document.getElementById('game-intelligence-title').textContent=data.title;
        document.getElementById('game-intelligence-result').textContent=(data.success?'Misja zakończona powodzeniem.':'Misja nie powiodła się.')+' Szansa po uwzględnieniu kontrwywiadu: '+data.chance;
        document.getElementById('game-intelligence-date').textContent='Zakończenie (Entenda): '+data.date;
        const entries=document.getElementById('game-intelligence-entries');entries.replaceChildren();
        for(const item of data.entries){const label=document.createElement('dt'),value=document.createElement('dd');label.textContent=item.label;value.textContent=item.value;entries.append(label,value);}
        root.open=false;intelligenceDialog.showModal();
    };

    async function load(page = 1, countOnly = false) {
        if (busy) return;
        busy = true;
        more.disabled = true;
        try {
            const url = new URL(root.dataset.url, window.location.origin);
            url.searchParams.set("page", String(page));
            const response = await fetch(url, { credentials: "same-origin", cache: "no-store" });
            if (!response.ok) throw new Error("Nie udało się pobrać powiadomień.");
            const data = await response.json();
            updateBadge(data.unread_count);
            if (countOnly) return;
            if (page === 1) {
                list.replaceChildren();
                displayed.clear();
            }
            data.items.forEach(item => {
                if (displayed.has(item.id)) return;
                displayed.add(item.id);
                const form = document.createElement("form");
                form.method = "post";
                form.action = item.open_url;
                const csrf = document.createElement("input");
                csrf.type = "hidden";
                csrf.name = "csrf_token";
                csrf.value = root.dataset.csrf;
                const button = document.createElement("button");
                button.type = "submit";
                button.className = "game-notification-item" + (item.unread ? " unread" : "");
                if (["war", "construction"].includes(item.severity)) button.classList.add("notification-" + item.severity);
                const icon = document.createElement("span");
                icon.className = "game-notification-icon";
                icon.setAttribute("aria-hidden", "true");
                if(item.icon_url){const image=document.createElement("img");image.src=item.icon_url;image.alt="";icon.append(image);}else icon.textContent = item.severity === "war" ? "❗" : "i";
                button.append(icon, document.createTextNode(item.text));
                if (item.unread) {
                    const fresh = document.createElement("span");
                    fresh.className = "game-notification-new";
                    fresh.textContent = "Nowe";
                    button.prepend(fresh);
                    button.setAttribute("aria-label", "Nieprzeczytane: " + item.text);
                }
                if (item.effects?.length) {
                    const effects = document.createElement("span");
                    effects.className = "game-event-effects";
                    appendEffects(effects, item.effects);
                    button.append(effects);
                }
                const date = document.createElement("small");
                date.textContent = item.received_at + " (Polska)";
                button.append(date);
                if (["DIPLOMACY", "GENERATED_EVENT", "INTELLIGENCE_REPORT"].includes(item.kind)) {
                    form.addEventListener("submit", async event => {
                        event.preventDefault();
                        button.disabled = true;
                        try {
                            const response = await fetch(form.action, { method: "POST", credentials: "same-origin", body: new FormData(form), headers: { Accept: "application/json" } });
                            const data = await response.json();
                            if (!response.ok) throw new Error();
                            if(item.kind === "INTELLIGENCE_REPORT") window.showIntelligenceReport(data.report);
                            else if (item.kind === "GENERATED_EVENT") showEvent(data.event);
                            else showDiplomacy(data.dialog);
                            load();
                        } catch (error) {
                            status.hidden = false;
                            status.textContent = "Nie udało się otworzyć powiadomienia. Spróbuj ponownie.";
                        } finally { button.disabled = false; }
                    });
                }
                form.append(csrf, button);
                if (item.unread) {
                    // Pojedyncze oznaczenie jako przeczytane bez otwierania powiadomienia (12 Nov 2026).
                    const mark = document.createElement("button");
                    mark.type = "button";
                    mark.className = "game-notification-mark";
                    mark.textContent = "Oznacz jako przeczytane";
                    mark.addEventListener("click", async event => {
                        event.preventDefault(); event.stopPropagation();
                        mark.disabled = true;
                        try {
                            const data = await markRead([item.id]);
                            button.classList.remove("unread");
                            button.querySelector(".game-notification-new")?.remove();
                            mark.remove();
                            updateBadge(data.unread_count);
                        } catch (error) { mark.disabled = false; status.hidden = false; status.textContent = "Nie udało się oznaczyć powiadomienia."; }
                    });
                    form.append(mark);
                }
                list.append(form);
            });
            // 12 Nov 2026: powiadomienie staje się przeczytane dopiero po kliknięciu (otwarcie oznacza je po stronie serwera).
            nextPage = data.next_page;
            more.hidden = !nextPage;
            status.hidden = displayed.size > 0;
            status.textContent = "Brak powiadomień.";
        } catch (error) {
            status.hidden = false;
            status.textContent = "Nie udało się pobrać powiadomień. Spróbuj ponownie, otwierając listę.";
        } finally {
            busy = false;
            more.disabled = false;
        }
    }
    async function markRead(ids, all = false) {
        const body = new FormData(); body.set("csrf_token", root.dataset.csrf);
        if (all) body.set("all", "1"); else ids.forEach(id => body.append("ids", String(id)));
        const response = await fetch(root.dataset.readUrl, { method: "POST", credentials: "same-origin", body });
        if (!response.ok) throw new Error();
        return response.json();
    }
    function updateBadge(count) {
        badge.textContent = String(count); badge.hidden = count === 0;
        toggle.setAttribute("aria-label", `Powiadomienia systemowe: ${count} nieprzeczytanych`);
        if (readAll) readAll.hidden = count === 0;
    }
    const readAll = document.getElementById("game-notification-read-all");
    if (readAll) readAll.addEventListener("click", async () => {
        readAll.disabled = true;
        try {
            const data = await markRead([], true);
            list.querySelectorAll(".unread").forEach(item => item.classList.remove("unread"));
            list.querySelectorAll(".game-notification-new,.game-notification-mark").forEach(node => node.remove());
            updateBadge(data.unread_count);
        } catch (error) { status.hidden = false; status.textContent = "Nie udało się oznaczyć powiadomień."; }
        finally { readAll.disabled = false; }
    });
    root.addEventListener("toggle", () => { if (root.open) load(); });
    root.addEventListener("keydown", event => {
        if (event.key === "Escape") { root.open = false; toggle.focus(); }
    });
    document.addEventListener("click", event => {
        if (root.open && !root.contains(event.target)) root.open = false;
    });
    more.addEventListener("click", () => { if (nextPage) load(nextPage); });
    document.addEventListener("visibilitychange", () => { if (!document.hidden) load(1, true); });
    load();
    setInterval(() => { if (!document.hidden) load(1, true); }, 30000);
})();
