const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const codes = ['wegiel_kamienny','ropa_naftowa','zloto','srebro','kamien','natsyt','kerbit','cemium','uran','zelazo'];
const quantities = ['0','200','201','500','501','1000','1001','10000','10001','9223372036854775807'];
const groups = [0,0,1,1,2,2,3,3,4,4];
class Element {
    constructor() { this.dataset = {}; this.children = []; this.textContent = ''; this.style = {}; }
    append(...items) { this.children.push(...items); }
    replaceChildren() { this.children = []; }
    setAttribute(key, value) { this[key] = value; }
    addEventListener(key, callback) { this[key] = callback; }
}
(async () => {
    const buttons = ['',...codes].map(code => Object.assign(new Element(), {dataset:{mapResource:code},textContent:code}));
    const regions = Object.fromEntries(quantities.map((quantity,index) => [String(index),{hasMinerals:index>0,deposits:codes.map(code => ({code,quantity}))}]));
    const config = {regions,selected:'3',countriesUrl:'/countries',regionsUrl:'/regions'};
    const legend = new Element();
    let styles, redraws = 0;
    const layer = {addTo() { return this; },getBounds() { return {isValid:()=>false}; },setStyle(fn) { styles=fn;redraws++; }};
    const context = {
        document:{getElementById:id=>id==='resource-map-config'?{textContent:JSON.stringify(config)}:id==='resources-map-legend'?legend:null,
            querySelectorAll:()=>buttons,createElement:()=>new Element(),createTextNode:text=>text},
        location:{href:'https://example.test/admin/surowce-naturalne',search:'',origin:'https://example.test'},history:{replaceState(){}},
        window:{L:true}, L:{CRS:{Simple:{}},map:()=>({setView(){}}),geoJSON:(data,options)=>{if(typeof options.style==='function')styles=options.style;return layer;}},
        fetch:async()=>({ok:true,json:async()=>({})}),URL,URLSearchParams,Intl,BigInt
    };
    vm.runInNewContext(fs.readFileSync('static/js/admin_natural_resources.js','utf8'),context);
    await new Promise(resolve=>setImmediate(resolve));
    for (const code of codes) {
        const button=buttons.find(item=>item.dataset.mapResource===code);button.click();
        assert.equal(button['aria-pressed'],'true');
        assert.equal(buttons.filter(item=>item['aria-pressed']==='true').length,1);
        const colors=quantities.map((_,index)=>styles({properties:{region_id:String(index)}}).fillColor);
        assert.equal(new Set(colors).size,5,code);
        for(let index=0;index<colors.length;index++)assert.equal(colors[index],colors[groups.indexOf(groups[index])],code+': '+quantities[index]);
        assert.equal(styles({properties:{region_id:'3'}}).color,'#ad2366');
        assert.equal(legend.children.length,7);
    }
    buttons[0].click();
    assert.equal(styles({properties:{region_id:'0'}}).fillColor,'#779ce4');
    assert.equal(styles({properties:{region_id:'1'}}).fillColor,'#218838');
    assert.equal(redraws,11);
    console.log('Resource filters: all 10 palettes, exact interval boundaries, BIGINT, selection and reset passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
