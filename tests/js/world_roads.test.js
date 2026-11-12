'use strict';
const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm'), path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../static/js/world_roads.js'), 'utf8');
function harness() {
    const elements = {toggleRoads: {checked: false, addEventListener(name, fn) {this.change = fn;}}, worldRoadsStatus: {}, worldRoadsLegend: {hidden: true}};
    const map = {visible: false, createPane() {}, getPane() {return {style: {}};}, removeLayer() {this.visible = false;}};
    const layer = {clearLayers() {}, addData(data) {this.data = data;}, addTo(map) {map.visible = true;}};
    let resolve, calls = 0, options;
    const context = {window: {}, document: {getElementById: id => elements[id], createElement: () => ({})},
        L: {geoJSON(data, opts) {options = opts; return layer;}},
        fetch: () => {calls++; return new Promise(r => {resolve = r;});}};
    vm.createContext(context); vm.runInContext(source, context);
    context.window.addWorldRoadsOverlay(map, '/wiki/mapa/drogi.geojson');
    return {elements, map, layer, get options() {return options;}, get calls() {return calls;},
        resolve: data => resolve({ok: true, headers: {get: () => 'application/json'}, json: async () => data}),
        reject: () => resolve({ok: false}),
        toggle: checked => {elements.toggleRoads.checked = checked; return elements.toggleRoads.change();}};
}
test('roads load lazily, display, hide and refresh on next enable', async () => {
    const h = harness(); assert.equal(h.calls, 0);
    const loading = h.toggle(true); h.resolve({features: [{id: 1}]}); await loading;
    assert.equal(h.map.visible, true); assert.equal(h.elements.worldRoadsLegend.hidden, false);
    await h.toggle(false); assert.equal(h.map.visible, false);
    const refresh = h.toggle(true); assert.equal(h.calls, 2); h.resolve({features: []}); await refresh;
    assert.match(h.elements.worldRoadsStatus.textContent, /Brak dróg/);
});
test('disabling while loading prevents the response from showing the overlay', async () => {
    const h = harness(), loading = h.toggle(true);
    await h.toggle(false); h.resolve({features: [{id: 1}]}); await loading;
    assert.equal(h.map.visible, false); assert.equal(h.elements.worldRoadsLegend.hidden, true);
});
test('failed loads reset the toggle and can be retried', async () => {
    const h = harness(), loading = h.toggle(true); h.reject(); await loading;
    assert.equal(h.elements.toggleRoads.checked, false); assert.match(h.elements.worldRoadsStatus.textContent, /Nie udało/);
    const retry = h.toggle(true); h.resolve({features: []}); await retry;
    assert.equal(h.map.visible, true);
});
test('road kinds have different styles and tooltip text is escaped through DOM text', () => {
    const h = harness(), motorway = h.options.style({properties: {kind: 'motorway'}}), national = h.options.style({properties: {kind: 'national'}});
    assert.notEqual(motorway.color, national.color); assert.ok(motorway.weight > national.weight);
    let label;
    h.options.onEachFeature({properties: {kind: 'motorway', id: 1, distanceKm: '12', country: '<img>'}}, {bindTooltip(node) {label = node;}});
    assert.equal(label.textContent, 'Autostrada #1 · 12 km · <img>'); assert.equal(label.innerHTML, undefined);
});
