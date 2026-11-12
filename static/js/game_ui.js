"use strict";
(() => {
    function place(anchor, panel) {
        if (!panel || !panel.getClientRects().length) return;
        const viewport = window.visualViewport;
        const width = viewport ? viewport.width : document.documentElement.clientWidth;
        const height = viewport ? viewport.height : window.innerHeight;
        const x = viewport ? viewport.offsetLeft : 0;
        const y = viewport ? viewport.offsetTop : 0;
        panel.style.maxWidth = Math.max(0, width - 24) + "px";
        const rect = anchor.getBoundingClientRect();
        const below = Math.max(0, y + height - rect.bottom - 20);
        const above = Math.max(0, rect.top - y - 20);
        const useBelow = below >= 160 || below >= above;
        panel.style.maxHeight = Math.max(0, (useBelow ? below : above)) + "px";
        const box = panel.getBoundingClientRect();
        panel.style.left = Math.max(x + 12, Math.min(rect.right - box.width, x + width - box.width - 12)) + "px";
        panel.style.top = (useBelow ? Math.max(y + 12, rect.bottom + 8) : Math.max(y + 12, rect.top - box.height - 8)) + "px";
    }
    let financeAnchor = null;
    const notifications = document.getElementById("game-notifications");
    const info = document.querySelector(".game-roi-info");
    const timeInfo=document.querySelector(".game-time-info");
    function reposition() {
        if (notifications?.open) place(notifications.querySelector("summary"), notifications.querySelector(".game-notification-dropdown"));
        if(timeInfo)place(timeInfo.querySelector("button"),timeInfo.querySelector(".game-time-tooltip"));
        if (info) place(info.querySelector("button"), info.querySelector(".game-roi-tooltip"));
        if (financeAnchor?.isConnected) place(financeAnchor, financeAnchor.querySelector(".finance-budget-tooltip"));
    }
    notifications?.addEventListener("toggle", reposition);
    if (notifications) new MutationObserver(reposition).observe(document.getElementById("game-notification-list"), { childList: true });
    if (info) {
        info.addEventListener("mouseenter", reposition);
        info.addEventListener("focusin", reposition);
        info.querySelector("button").addEventListener("click", () => { info.classList.toggle("is-open"); reposition(); });
        info.addEventListener("keydown", event => { if (event.key === "Escape") { info.classList.remove("is-open"); info.querySelector("button").blur(); } });
        document.addEventListener("click", event => {
            if (!info.contains(event.target)) {
                info.classList.remove("is-open");
                if (document.activeElement === info.querySelector("button")) info.querySelector("button").blur();
            }
        });
    }
    if(timeInfo){timeInfo.addEventListener('mouseenter',reposition);timeInfo.addEventListener('focusin',reposition);timeInfo.querySelector('button').onclick=()=>{const open=timeInfo.classList.toggle('is-open');if(!open)timeInfo.querySelector('button').blur();reposition();};document.addEventListener('click',event=>{if(!timeInfo.contains(event.target)){timeInfo.classList.remove('is-open');if(document.activeElement===timeInfo.querySelector('button'))timeInfo.querySelector('button').blur();}});timeInfo.addEventListener('keydown',event=>{if(event.key==='Escape'){timeInfo.classList.remove('is-open');timeInfo.querySelector('button').blur();}});}
    function positionBudgetTooltip(event) {
        const segment = event.target instanceof Element ? event.target.closest(".finance-budget-segment") : null;
        if (segment) {
            financeAnchor = segment;
            reposition();
        }
    }
    document.addEventListener("pointerover", positionBudgetTooltip);
    document.addEventListener("focusin", positionBudgetTooltip);
    window.addEventListener("resize", reposition);
    window.addEventListener("scroll", reposition, { passive: true, capture: true });
    window.visualViewport?.addEventListener("resize", reposition);
    window.visualViewport?.addEventListener("scroll", reposition);
})();
