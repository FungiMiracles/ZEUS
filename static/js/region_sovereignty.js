(() => {
    'use strict';
    document.querySelectorAll('[data-sovereignty-open]').forEach(link => {
        link.addEventListener('click', event => {
            event.preventDefault();
            const dialog = document.getElementById(link.dataset.sovereigntyOpen);
            if (!dialog) return;
            document.getElementById('dropdownMenu')?.style.setProperty('display', 'none');
            dialog.showModal();
        });
    });
    document.querySelectorAll('.region-sovereignty-dialog').forEach(dialog => {
        dialog.querySelector('[data-sovereignty-close]').addEventListener('click', () => dialog.close());
        dialog.querySelector('form').addEventListener('submit', () => {
            dialog.querySelector('button[type="submit"]').disabled = true;
        });
    });
})();
