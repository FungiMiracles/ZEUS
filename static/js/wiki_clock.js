(() => {
    'use strict';
    const parseTime = value => Date.parse(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : value + 'Z');
    const clocks = Array.from(document.querySelectorAll('.entenda-clock, #game-entenda-clock')).map(element => ({
        element, start: parseTime(element.dataset.entenda || ''), realStart: performance.now(),
        multiplier: Number(element.dataset.timeMultiplier), revision: Number(element.dataset.clockRevision || 0),
    }));
    const controls = document.querySelector('.entenda-speed-controls');
    const status = document.querySelector('.entenda-speed-status');
    const stateUrl = clocks.find(clock => clock.element.dataset.clockStateUrl)?.element.dataset.clockStateUrl;
    const passwordDialog = document.querySelector('.clock-password-dialog');
    function requestPassword() {
        return new Promise(resolve => {
            const input = passwordDialog.querySelector('input');
            const form = passwordDialog.querySelector('form');
            input.value = '';
            passwordDialog.returnValue = '';
            form.onsubmit = event => { event.preventDefault(); passwordDialog.close('confirm'); };
            passwordDialog.querySelector('[data-clock-cancel]').onclick = () => passwordDialog.close();
            passwordDialog.addEventListener('close', () => {
                const password = passwordDialog.returnValue === 'confirm' ? input.value : null;
                input.value = '';
                resolve(password);
            }, {once:true});
            passwordDialog.showModal();
            input.focus();
        });
    }
    let changing = false, syncing = false;
    function update() {
        for (const clock of clocks) {
            if (!Number.isFinite(clock.start) || !Number.isFinite(clock.multiplier) || clock.multiplier < 0) continue;
            const now = new Date(clock.start + (performance.now() - clock.realStart) * clock.multiplier);
            const elapsed = now.getUTCHours() * 3600000 + now.getUTCMinutes() * 60000
                + now.getUTCSeconds() * 1000 + now.getUTCMilliseconds();
            const fraction = elapsed / 86400000;
            clock.element.style.setProperty('--day-progress', (fraction * 360) + 'deg');
            const pad = value => String(value).padStart(2, '0');
            clock.element.textContent = `${pad(now.getUTCDate())}.${pad(now.getUTCMonth() + 1)}.${now.getUTCFullYear()} CE`;
            document.querySelectorAll('.day-progress-fill').forEach(bar => { bar.style.width = (fraction * 100) + '%'; });
        }
    }
    function apply(snapshot) {
        if (!Number.isFinite(parseTime(snapshot.entenda || '')) || ![0,6,12,24,36].includes(snapshot.multiplier)) throw Error('clock');
        if (clocks.some(clock => snapshot.revision < clock.revision)) return;
        for (const clock of clocks) {
            if (snapshot.revision < clock.revision) continue;
            clock.start = parseTime(snapshot.entenda); clock.realStart = performance.now();
            clock.multiplier = snapshot.multiplier; clock.revision = snapshot.revision;
            clock.element.dataset.timeMultiplier = String(snapshot.multiplier);
            clock.element.title = snapshot.description || '';
        }
        controls?.querySelectorAll('[data-clock-speed]').forEach(button => {
            button.setAttribute('aria-pressed', String(Number(button.dataset.clockSpeed) === snapshot.multiplier));
        });
        const tooltip = document.getElementById('game-time-tooltip');
        if (tooltip) tooltip.textContent = snapshot.description || '';
        update();
    }
    async function sync() {
        if (!stateUrl || changing || syncing || document.hidden) return;
        syncing = true;
        try {
            const response = await fetch(stateUrl, {credentials:'same-origin', cache:'no-store'});
            if (response.ok && !changing) apply(await response.json());
        } catch (error) { /* Keep displaying the last server snapshot; retry next tick. */ }
        finally { syncing = false; }
    }
    controls?.querySelectorAll('[data-clock-speed]').forEach(button => button.addEventListener('click', async () => {
        if (changing || !clocks.length) return;
        changing = true; status.textContent = '';
        controls.querySelectorAll('button').forEach(item => {item.disabled = true;});
        try {
            const password = await requestPassword();
            if (password === null) return;
            const response = await fetch(controls.dataset.clockChangeUrl, {
                method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json','X-CSRF-Token':controls.dataset.csrf},
                body:JSON.stringify({multiplier:Number(button.dataset.clockSpeed), revision:clocks[0].revision, password}),
            });
            const result = await response.json();
            if (!response.ok) {
                if (result.clock) apply(result.clock);
                throw Error(result.error || 'Nie udało się zmienić tempa zegara. Odśwież stronę.');
            }
            apply(result);
        } catch (error) { status.textContent = error.message || 'Nie udało się zmienić tempa zegara.'; }
        finally { changing = false; controls.querySelectorAll('button').forEach(item => {item.disabled = false;}); }
    }));
    update();
    setInterval(update, 250);
    setInterval(sync, 5000);
    document.addEventListener('visibilitychange', () => {update(); sync();});
    sync();
})();
