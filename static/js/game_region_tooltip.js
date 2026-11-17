(() => {
    'use strict';
    const active = new WeakMap();
    function bind(layer, content, options = {}) {
        const {enabled = () => true, ...appearance} = options;
        const tooltip = L.tooltip({interactive: true, direction: 'top', offset: [0, -12],
            className: 'industry-deposit-tooltip', ...appearance}, layer);
        let timer, currentMap, connectedMap;
        const cancelClose = () => { clearTimeout(timer); timer = undefined; };
        const close = () => {
            cancelClose();
            tooltip.remove();
            if (currentMap && active.get(currentMap)?.tooltip === tooltip) active.delete(currentMap);
            currentMap = undefined;
        };
        const scheduleClose = () => { cancelClose(); timer = setTimeout(close, 250); };
        const open = event => {
            if (!enabled() || !layer._map) return;
            cancelClose();
            const map = layer._map;
            if (active.get(map)?.tooltip === tooltip) return;
            active.get(map)?.close();
            currentMap = map;
            // Anchor once at entry, above the pointer. Moving into the card must not move it.
            tooltip.setContent(typeof content === 'function' ? content() : content);
            tooltip.setLatLng(event.latlng || layer.getBounds().getCenter()).addTo(map);
            active.set(map, {tooltip, close});
        };
        tooltip.on('add', () => {
            const element = tooltip.getElement();
            L.DomEvent.disableClickPropagation(element);
            L.DomEvent.disableScrollPropagation(element);
            element.addEventListener('mouseenter', cancelClose);
            element.addEventListener('mouseleave', scheduleClose);
            element.addEventListener('focusin', cancelClose);
            element.addEventListener('focusout', scheduleClose);
        });
        layer.on({mouseover: open, mouseout: scheduleClose, click: open});
        const connect = () => { connectedMap = layer._map; connectedMap?.on('movestart', close); };
        layer.on('add', connect);
        layer.on('remove', () => { connectedMap?.off('movestart', close); connectedMap = undefined; close(); });
        connect();
        return tooltip;
    }
    window.GameRegionTooltip = {
        bind,
        isOpen: map => !!map && active.has(map),
        close: map => { if (map) active.get(map)?.close(); }
    };
})();
