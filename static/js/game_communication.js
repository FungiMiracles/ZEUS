"use strict";
(() => {
    const dialog = document.getElementById("game-mail-dialog");
    if (!dialog) return;
    const toggle = document.getElementById("game-mail-toggle");
    const badge = document.getElementById("game-mail-count");
    const list = document.getElementById("game-mail-list");
    const folder = document.getElementById("game-mail-folder");
    const more = document.getElementById("game-mail-more");
    const view = document.getElementById("game-mail-view");
    const form = document.getElementById("game-mail-compose");
    const recipient = document.getElementById("game-mail-recipient");
    const content = document.getElementById("game-mail-content");
    const status = document.getElementById("game-mail-status");
    let nextPage = null;
    let listRequest = 0;
    let detailRequest = 0;
    let selectedId = null;
    let current = null;
    let addresses = [];
    let sending = false;
    const displayed = new Set();
    async function api(url, options = {}) {
        const response = await fetch(url, { credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" }, ...options });
        let data;
        try { data = await response.json(); } catch { throw new Error("Nie udało się połączyć z pocztą. Odśwież stronę i spróbuj ponownie."); }
        if (!response.ok) throw new Error(data.error || "Nie udało się wykonać operacji.");
        return data;
    }
    function csrfBody() { const body = new FormData(); body.set("csrf_token", dialog.dataset.csrf); return body; }
    function updateBadge(count) {
        badge.hidden = count === 0;
        badge.textContent = String(count);
        toggle.setAttribute("aria-label", `Prywatne wiadomości: ${count} nieprzeczytanych`);
    }
    function identity(message) {
        const row = document.createElement("span");
        row.className = "game-mail-identity";
        const flag = document.createElement("img");
        flag.src = message.sender_flag;
        flag.alt = "Flaga państwa " + message.sender_country;
        const text = document.createElement("span");
        text.textContent = message.sender_country + " · " + message.sender_name;
        row.append(flag, text);
        return row;
    }
    async function loadList(page = 1) {
        const requestId = ++listRequest;
        const selectedFolder = folder.value;
        const url = new URL(dialog.dataset.url, window.location.origin);
        url.searchParams.set("folder", selectedFolder);
        url.searchParams.set("page", String(page));
        more.disabled = true;
        try {
            const data = await api(url);
            if (requestId !== listRequest) return;
            updateBadge(data.unread_count);
            if (page === 1) { list.replaceChildren(); displayed.clear(); }
            data.items.forEach(message => {
                if (displayed.has(message.id)) return;
                displayed.add(message.id);
                const button = document.createElement("button");
                button.type = "button";
                button.className = "game-mail-item" + (message.unread ? " unread" : "");
                button.dataset.messageId = String(message.id);
                button.setAttribute("aria-pressed", String(message.id === selectedId));
                button.append(identity(message));
                if (!message.incoming) {
                    const target = document.createElement("small");
                    target.textContent = "Do: " + message.recipient_country + " · " + message.recipient_name;
                    button.append(target);
                }
                const date = document.createElement("small");
                date.textContent = message.received_at + " (Polska)";
                const relation = document.createElement("small");
                relation.textContent = message.relation;
                button.append(date, relation);
                if (message.unread) {
                    const unread = document.createElement("small");
                    unread.textContent = "Nieprzeczytana";
                    button.append(unread);
                }
                button.addEventListener("click", () => openMessage(message.detail_url));
                list.append(button);
            });
            if (!displayed.size) list.textContent = "Brak wiadomości w tym folderze.";
            nextPage = data.next_page;
            more.hidden = !nextPage;
        } catch (error) { if (requestId === listRequest) status.textContent = error.message; }
        finally { if (requestId === listRequest) more.disabled = false; }
    }
    function renderMessage(message) {
        current = message;
        selectedId = message.id;
        form.hidden = true;
        view.hidden = false;
        dialog.classList.remove("game-mail-composing");
        dialog.classList.add("game-mail-reading");   // telefon: pełnoekranowa treść zamiast listy (19 Nov 2026)
        view.replaceChildren();
        const heading = document.createElement("h3");
        heading.textContent = "Wiadomość od: " + message.sender_name;
        const date = document.createElement("p");
        date.textContent = message.received_at + " (Polska) · " + message.relation;
        const body = document.createElement("p");
        body.className = "game-preserve-lines";
        body.textContent = message.content;
        view.append(heading, identity(message), date, body);
        if (message.reply_to_id) {
            const source = document.createElement("button");
            source.type = "button";
            source.textContent = "Pokaż wiadomość źródłową";
            source.addEventListener("click", () => openMessage(dialog.dataset.url + "/" + message.reply_to_id));
            view.append(source);
        }
        if (message.incoming) {
            const reply = document.createElement("button");
            reply.type = "button";
            reply.textContent = "Odpowiedz";
            reply.disabled = !addresses.some(item => item.id === message.sender_id);
            if (reply.disabled) reply.title = "Nadawca nie ma obecnie aktywnego konta z przypisanym państwem.";
            reply.addEventListener("click", () => compose(message));
            view.append(reply);
        }
        list.querySelectorAll("[data-message-id]").forEach(button => button.setAttribute("aria-pressed", String(Number(button.dataset.messageId) === message.id)));
    }
    async function openMessage(url) {
        const requestId = ++detailRequest;
        status.textContent = "Ładowanie wiadomości…";
        try {
            const data = await api(url);
            if (requestId !== detailRequest) return;
            renderMessage(data.message);
            status.textContent = "";
            if (data.message.unread) {
                await api(data.message.read_url, { method: "POST", body: csrfBody() });
                await loadList();
            }
            view.scrollIntoView({ block: "nearest" });
        } catch (error) { if (requestId === detailRequest) status.textContent = error.message; }
    }
    function countContent() {
        const count = Array.from(content.value).length;
        document.getElementById("game-mail-limit").textContent = `${count} / 3000`;
        content.setCustomValidity(count > 3000 ? "Maksymalnie 3000 znaków razem ze spacjami." : !content.value.trim() ? "Wiadomość nie może być pusta." : "");
    }
    let composeFromMessage = false;
    function compose(source = null) {
        composeFromMessage = dialog.classList.contains("game-mail-reading");
        ++detailRequest;
        view.hidden = true;
        form.hidden = false;
        dialog.classList.add("game-mail-composing");
        form.reset();
        recipient.disabled = Boolean(source);
        recipient.value = source ? String(source.sender_id) : "";
        document.getElementById("game-mail-reply-id").value = source ? String(source.id) : "";
        document.getElementById("game-mail-compose-title").textContent = source ? "Odpowiedz na wiadomość" : "Nowa wiadomość";
        document.getElementById("game-mail-reply-context").textContent = source ? "Odpowiedź na wiadomość od " + source.sender_name + " z " + source.received_at : "";
        status.textContent = "";
        countContent();
        (source ? content : recipient).focus();
    }
    async function loadAddresses() {
        const data = await api(dialog.dataset.recipientsUrl);
        addresses = data.items;
        const placeholder = document.createElement("option");
        placeholder.value = "";
        placeholder.textContent = "Wybierz państwo i użytkownika";
        recipient.replaceChildren(placeholder);
        addresses.forEach(item => {
            const option = document.createElement("option");
            option.value = String(item.id);
            option.textContent = item.country_name + " · " + item.name;
            recipient.append(option);
        });
    }
    function showList() {
        dialog.classList.remove("game-mail-reading");
        list.querySelector('[aria-pressed="true"]')?.focus({ preventScroll: false });
    }
    document.getElementById("game-mail-back").addEventListener("click", showList);
    toggle.addEventListener("click", async () => {
        dialog.classList.remove("game-mail-reading", "game-mail-composing");
        dialog.showModal();
        status.textContent = "Ładowanie…";
        try { await loadAddresses(); await loadList(); status.textContent = ""; }
        catch (error) { status.textContent = error.message; }
    });
    document.getElementById("game-mail-close").addEventListener("click", () => dialog.close());
    document.getElementById("game-mail-new").addEventListener("click", () => compose());
    document.getElementById("game-mail-cancel").addEventListener("click", () => {
        form.hidden = true;
        view.hidden = false;
        dialog.classList.remove("game-mail-composing");
        if (current && composeFromMessage) renderMessage(current);   // telefon: powrót tam, skąd zaczęto pisać
        else if (current && !window.matchMedia("(max-width: 650px)").matches) renderMessage(current);
    });
    folder.addEventListener("change", () => { ++detailRequest; dialog.classList.remove("game-mail-reading"); loadList(); });
    more.addEventListener("click", () => { if (nextPage) loadList(nextPage); });
    content.addEventListener("input", countContent);
    form.addEventListener("submit", async event => {
        event.preventDefault();
        if (sending) return;
        countContent();
        if (!form.reportValidity()) return;
        const body = new FormData(form);
        body.set("csrf_token", dialog.dataset.csrf);
        body.set("recipient_id", recipient.value);
        const button = form.querySelector('[type="submit"]');
        sending = true;
        button.disabled = true;
        try {
            const data = await api(dialog.dataset.url, { method: "POST", body });
            form.reset();
            form.hidden = true;
            view.hidden = false;
            dialog.classList.remove("game-mail-composing");
            folder.value = "sent";
            await loadList();
            await openMessage(dialog.dataset.url + "/" + data.id);
            status.textContent = data.message;
        } catch (error) { status.textContent = error.message; }
        finally { sending = false; button.disabled = false; }
    });
    async function refreshCount() {
        try { const data = await api(dialog.dataset.url); updateBadge(data.unread_count); }
        catch { /* Formularz zachowuje treść przy chwilowym braku połączenia. */ }
    }
    refreshCount();
    setInterval(() => { if (!document.hidden) refreshCount(); }, 30000);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshCount(); });
})();
