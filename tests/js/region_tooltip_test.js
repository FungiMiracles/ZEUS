(source => {
    const assert = (condition, message) => { if (!condition) throw Error(message); };
    class Events {
        constructor() { this.events = {}; }
        on(name, handler) {
            if (typeof name === 'object') { for (const [key, fn] of Object.entries(name)) this.on(key, fn); }
            else (this.events[name] ||= new Set()).add(handler);
            return this;
        }
        off(name, handler) { this.events[name]?.delete(handler); }
        fire(name, event = {}) { for (const fn of this.events[name] || []) fn(event); }
    }
    let sequence = 0;
    const timers = new Map(), window = {};
    const later = fn => { timers.set(++sequence, fn); return sequence; };
    const cancel = id => timers.delete(id);
    const flush = () => { const pending = [...timers.values()]; timers.clear(); pending.forEach(fn => fn()); };
    class Tooltip extends Events {
        constructor() { super(); this.element = new Events(); this.element.addEventListener = this.element.on.bind(this.element); }
        setContent(content) { this.content = content; return this; }
        setLatLng(point) { this.point = point; return this; }
        addTo(map) { this.map = map; this.fire('add'); return this; }
        remove() { this.map = null; }
        getElement() { return this.element; }
    }
    const L = {tooltip: () => new Tooltip(), DomEvent: {disableClickPropagation() {}, disableScrollPropagation() {}}};
    new Function('window', 'L', 'setTimeout', 'clearTimeout', source)(window, L, later, cancel);
    const api = window.GameRegionTooltip, map = new Events();
    const layer = new Events(); layer._map = map;
    let rendered = 0;
    const tooltip = api.bind(layer, () => ++rendered);
    const point = {lat: 1, lng: 2};
    layer.fire('mouseover', {latlng: point});
    assert(api.isOpen(map), 'Hover opens the card');
    layer.fire('mouseout');
    assert(api.isOpen(map), 'Leaving the region does not immediately remove the card');
    tooltip.element.fire('mouseenter'); flush();
    assert(api.isOpen(map), 'Moving onto the card keeps it open');
    layer.fire('mouseover', {latlng: {lat: 2, lng: 3}});
    assert(tooltip.point === point && rendered === 1, 'Reentry keeps the anchor and content stable');
    tooltip.element.fire('mouseleave'); flush();
    assert(!api.isOpen(map), 'Leaving both card and region closes it');
    layer.fire('click', {latlng: point});
    assert(api.isOpen(map), 'Touch/click opens the card');
    map.fire('movestart');
    assert(!api.isOpen(map), 'Moving the map dismisses the card');
    const other = new Events(); other._map = map;
    api.bind(other, 'Other');
    layer.fire('mouseover', {latlng: point}); other.fire('mouseover', {latlng: point});
    assert(!tooltip.map && api.isOpen(map), 'Only one card is open per map');
    api.close(map);
    layer.fire('mouseover', {latlng: point}); layer.fire('remove'); flush();
    assert(!api.isOpen(map), 'Removing a region cleans up its card');
    const blocked = new Events(); blocked._map = map;
    api.bind(blocked, 'Blocked', {enabled: () => false});
    blocked.fire('mouseover', {latlng: point});
    assert(!api.isOpen(map), 'Placement can disable region cards');
    return 'Tooltip interaction checks passed';
})
