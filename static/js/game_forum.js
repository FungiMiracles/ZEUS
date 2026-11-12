"use strict";

(() => {
    const picker = document.getElementById("forum-recipient-picker");
    if (picker) {
        const summary = picker.querySelector("summary");
        const value = document.getElementById("forum-recipient-value");
        function updateRecipients() {
            const selected = picker.querySelectorAll('input[name="recipient_id"]:checked');
            value.replaceChildren();
            selected.forEach(input => {
                const label = input.closest("label").querySelector(".forum-recipient-label");
                value.append(label.cloneNode(true));
            });
            if (!selected.length) value.textContent = "Do wszystkich";
        }
        picker.addEventListener("change", updateRecipients);
        updateRecipients();
        picker.addEventListener("keydown", event => {
            if (event.key === "Escape") {
                picker.open = false;
                summary.focus();
            }
        });
    }

    const content = document.getElementById("forum-content");
    const count = document.getElementById("forum-count");
    if (!content || !count) return;

    function updateCount() {
        // Tak jak len() na serwerze: punkty Unicode, także dla emoji.
        const length = Array.from(content.value).length;
        count.textContent = `${length} / 1000`;
        content.setCustomValidity(
            length > 1000 ? "Wiadomość może mieć maksymalnie 1000 znaków razem ze spacjami."
                : !content.value.trim() ? "Wiadomość nie może być pusta." : ""
        );
    }
    content.addEventListener("input", updateCount);
    updateCount();
})();
