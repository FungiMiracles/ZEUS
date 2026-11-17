/* 17 Nov 2026: crypto.randomUUID istnieje tylko w bezpiecznym kontekście (HTTPS/localhost) i w nowszych przeglądarkach.
   Uzupełnienie oparte na crypto.getRandomValues (dostępne wszędzie) — identyfikatory żądań działają także przez HTTP. */
(function () {
    "use strict";
    var c = window.crypto || window.msCrypto;
    if (!c || typeof c.randomUUID === "function") return;
    var uuid = function () {
        var b = new Uint8Array(16);
        c.getRandomValues(b);
        b[6] = (b[6] & 15) | 64;
        b[8] = (b[8] & 63) | 128;
        var h = Array.prototype.map.call(b, function (x) { return (x + 256).toString(16).slice(1); }).join("");
        return h.slice(0, 8) + "-" + h.slice(8, 12) + "-" + h.slice(12, 16) + "-" + h.slice(16, 20) + "-" + h.slice(20);
    };
    try { Object.defineProperty(c, "randomUUID", { value: uuid, configurable: true, writable: true }); }
    catch (error) { try { c.randomUUID = uuid; } catch (ignored) { /* brak możliwości uzupełnienia */ } }
})();
