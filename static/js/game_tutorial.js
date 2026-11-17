"use strict";
// 15 Nov 2026: samouczek — okna pokazywane po kolei (powitanie, potem komunikat sekcji); zamknięcie (przycisk lub Esc)
// zapisuje odczyt danego komunikatu, więc każdy pojawia się tylko raz.
(() => {
    const dialogs = [...document.querySelectorAll("dialog.game-tutorial-dialog")];
    if (!dialogs.length || typeof dialogs[0].showModal !== "function") return;
    function save(dialog) {
        const body = new FormData();
        body.set("csrf_token", dialog.dataset.csrf || "");
        body.set("tutorial", dialog.dataset.tutorial);
        fetch(dialog.dataset.url, { method: "POST", credentials: "same-origin", body, headers: { Accept: "application/json" } }).catch(() => {});
    }
    function show(index) {
        const dialog = dialogs[index];
        if (!dialog) return;
        const button = dialog.querySelector(".game-tutorial-close");
        button.addEventListener("click", () => dialog.close(), { once: true });
        dialog.addEventListener("close", () => { save(dialog); show(index + 1); }, { once: true });
        dialog.showModal();
        button.focus();
    }
    show(0);
})();
