'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../../static/js/game_military.js'),'utf8');
function section(start,end){return source.slice(source.indexOf(start),source.indexOf(end,source.indexOf(start)));}
function harness(){
    const layer=()=>({items:[],clearLayers(){this.items=[];}}),node=()=>({append(){},prepend(){},style:{},setAttribute(){}});
    const context={window:{},mapFilters:new Set(['air','naval','land','nuclear','defenses','mines']),config:{mode:'war',countryId:1,resources:{},regions:{},mineralIcons:{gold:{icon:'gold'}},visibleBases:['air','naval','land','nuclear'].map((kind,i)=>({id:i,kind,position:[i,0],countryId:1,health:100,garrison:{}})),visibleMines:[{id:1,resource:'gold',position:[0,0],health:100,ready:true}],defenses:[{id:1,targetKind:'region',position:[0,0],health:100,level:1,ammunition:10,capacity:100,efficiency:30}]},baseLayer:layer(),mineLayer:layer(),defenseLayer:layer(),bindObjectTooltip:(marker,content)=>marker.bindTooltip(content),make:node,image:node,healthBar:node,baseName:()=>'',baseIcon:()=>'',number:String,L:{divIcon:x=>x,marker:()=>({bindTooltip(){return this;},on(){return this;},addTo(layer){layer.items.push(this);return this;}})}};
    vm.createContext(context);
    vm.runInContext(section('    function drawDefenses(){','    function sourceBases(')+section('    function drawMines(){','    const shipLayer='),context);
    return context;
}
test('map filters support arbitrary combinations, including none, across redraws',()=>{
    const c=harness();c.drawBases();c.drawMines();c.drawDefenses();assert.equal(c.baseLayer.items.length,4);assert.equal(c.mineLayer.items.length,1);assert.equal(c.defenseLayer.items.length,1);
    c.mapFilters=new Set(['air','mines']);c.drawBases();c.drawMines();c.drawDefenses();assert.equal(c.baseLayer.items.length,1);assert.equal(c.mineLayer.items.length,1);assert.equal(c.defenseLayer.items.length,0);
    c.drawBases();assert.equal(c.baseLayer.items.length,1);
    c.mapFilters.clear();c.drawBases();c.drawMines();assert.equal(c.baseLayer.items.length,0);assert.equal(c.mineLayer.items.length,0);
    c.mapFilters.add('nuclear');c.drawBases();assert.equal(c.baseLayer.items.length,1);
});
test('defense screen cannot reveal foreign bases through filters',()=>{
    const c=harness();c.config.mode='defense';c.config.visibleBases[0].countryId=2;c.drawBases();assert.equal(c.baseLayer.items.length,3);
});
test('toggle buttons expose their state and redraw each object layer',()=>{
    let click;const control={dataset:{mapFilter:'mines'},addEventListener:(_,fn)=>click=fn,setAttribute:(key,value)=>control[key]=value};
    const c={allFilters:null,document:{querySelectorAll:()=>[control]},mapFilters:new Set(['mines']),selectedTarget:null,drawBases(){},drawDefenses(){},drawMines(){},drawFactories(){},drawPower(){},saveMapFilters(){}};vm.createContext(c);
    const start=source.indexOf("    document.querySelectorAll('[data-map-filter]')");vm.runInContext(source.slice(start,source.indexOf('    const vesselName=',start)),c);
    click();assert.equal(control['aria-pressed'],'false');assert.equal(c.mapFilters.has('mines'),false);click();assert.equal(control['aria-pressed'],'true');
});

test('select all toggles eight independent kinds together',()=>{
 const controls=['air','naval','land','nuclear','defenses','mines','factories','power'].map(kind=>({dataset:{mapFilter:kind},addEventListener(){},setAttribute(name,value){this[name]=value;}})),all={};
 const c={document:{getElementById:()=>all,querySelectorAll:()=>controls},mapFilterKinds:controls.map(c=>c.dataset.mapFilter),mapFilters:new Set(controls.map(item=>item.dataset.mapFilter)),selectedTarget:null,drawBases(){},drawDefenses(){},drawMines(){},drawFactories(){},drawPower(){},saveMapFilters(){}};
 vm.createContext(c);const start=source.indexOf('    const allFilters=');vm.runInContext(source.slice(start,source.indexOf('    const vesselName=',start)),c);
 all.onclick();assert.equal(c.mapFilters.size,0);assert.equal(all.textContent,'Zaznacz wszystkie');all.onclick();assert.equal(c.mapFilters.size,8);assert.equal(all.textContent,'Odznacz wszystkie');
});

function persistence(storage,mode='defense',countryId=1){
 const context={config:{mode,countryId},sessionStorage:storage};vm.createContext(context);
 vm.runInContext(section('    const mapFilterKinds=','    function updateReadiness('),context);
 return {values:()=>JSON.parse(vm.runInContext('JSON.stringify([...mapFilters])',context)),choose:kinds=>{context.chosen=kinds;vm.runInContext('mapFilters.clear();for(const kind of chosen)mapFilters.add(kind);saveMapFilters();',context);}};
}
function memoryStorage(){const data=new Map();return {getItem:key=>data.get(key)||null,setItem:(key,value)=>data.set(key,value)};}
test('filters survive new page instances after actions, including the empty selection',()=>{
 const storage=memoryStorage();
 for(const mode of ['defense','war']){
  const page=persistence(storage,mode);assert.equal(page.values().length,8);
  page.choose(['naval','defenses']);assert.deepEqual(persistence(storage,mode).values(),['naval','defenses']);
  page.choose([]);assert.deepEqual(persistence(storage,mode).values(),[]);
 }
});
test('filter preferences are isolated by country and screen',()=>{
 const storage=memoryStorage();persistence(storage).choose(['mines']);
 assert.equal(persistence(storage,'war').values().length,8);
 assert.equal(persistence(storage,'defense',2).values().length,8);
 assert.deepEqual(persistence(storage).values(),['mines']);
});
test('invalid or inaccessible session storage falls back to all filters',()=>{
 for(const raw of ['{','null','{}','[null]','["unknown"]'])assert.equal(persistence({getItem:()=>raw}).values().length,8);
 const denied={getItem(){throw Error('denied');},setItem(){throw Error('denied');}};
 const page=persistence(denied);assert.equal(page.values().length,8);assert.doesNotThrow(()=>page.choose(['naval']));assert.deepEqual(page.values(),['naval']);
});
