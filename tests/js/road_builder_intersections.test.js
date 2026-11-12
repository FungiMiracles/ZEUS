'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../../static/js/road_builder.js'),'utf8');
function harness(roads){const c={roads,map:{latLngToContainerPoint:point=>({x:point[1],y:point[0]}),containerPointToLatLng:point=>({lng:point[0],lat:point[1]})}};vm.createContext(c);vm.runInContext(source.slice(source.indexOf('function snapPoint('),source.indexOf('function drawDraft(')),c);return c;}
test('an endpoint can snap to the exact intersection of roads of either kind',()=>{const c=harness([{id:1,kind:'motorway',path:[[0,50],[100,50]]},{id:2,kind:'national',path:[[50,0],[50,100]]}]);assert.deepEqual(Array.from(c.snapPoint([53,52])),[50,50]);});
test('a point can start from the middle of an existing segment, while distant points stay free',()=>{const c=harness([{id:1,path:[[0,0],[100,0]]}]);assert.deepEqual(Array.from(c.snapPoint([37,4])),[37,0]);assert.deepEqual(Array.from(c.snapPoint([37,30])),[37,30]);});
test('adjacent curve segments do not turn ordinary vertices into false intersections',()=>{const c=harness([{id:1,path:[[0,0],[50,2],[100,0]]}]);const point=c.snapPoint([30,1]);assert.ok(Math.abs(point[0]-30)<1);assert.notEqual(point[0],50);});

test('editable curve passes both one-third handles and preserves endpoints',()=>{const c=harness([]);c.start=[0,0];c.end=[90,0];c.controls=[[30,12],[60,-8]];const points=c.interpolatePath();assert.equal(points.length,25);for(const [i,p] of [[0,c.start],[8,c.controls[0]],[16,c.controls[1]],[24,c.end]])assert.ok(points[i].every((n,j)=>Math.abs(n-p[j])<1e-9));c.controls[0]=[30,22];assert.ok(Math.abs(c.interpolatePath()[8][1]-22)<1e-9);});
