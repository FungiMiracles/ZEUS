'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../../static/js/game_notifications.js'),'utf8');
function harness(){
    const nodes=new Map();
    function node(){return {dataset:{},children:[],listeners:{},classList:{add(){},remove(){}},append(...children){this.children.push(...children);},replaceChildren(){this.children=[];},setAttribute(){},addEventListener(name,fn){this.listeners[name]=fn;},querySelectorAll(){return [];}};}
    const document={hidden:false,listeners:{},getElementById(id){if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);},createElement:node,createTextNode:text=>({text}),addEventListener(name,fn){this.listeners[name]=fn;}};
    const root=document.getElementById('game-notifications');root.open=false;root.dataset={url:'/notices',readUrl:'/read',csrf:'csrf'};
    const requests=[];
    const context={document,window:{location:{origin:'https://uat.test'},dispatchEvent(){}},URL,FormData,setInterval(){},MutationObserver:class{},Event,fetch:async(url,options)=>{requests.push({url:String(url),options});return {ok:true,json:async()=>String(url)==='/read'?{unread_count:3}:{unread_count:4,next_page:2,items:[{id:1,text:'Budowa',kind:'SYSTEM',severity:'construction',unread:true,open_url:'/open',received_at:'teraz'}]}};}};
    vm.createContext(context);vm.runInContext(source,context);
    return {root,document,nodes,requests,flush:async()=>{for(let i=0;i<12;i++)await Promise.resolve();}};
}
test('prefetch and background polling keep unseen notifications unread; opening list reads them',async()=>{
    const c=harness();await c.flush();assert.equal(c.requests.filter(r=>r.url==='/read').length,0);
    c.root.open=true;c.root.listeners.toggle();await c.flush();assert.equal(c.requests.filter(r=>r.url==='/read').length,1);
    const request=c.requests.find(r=>r.url==='/read');assert.equal(request.options.method,'POST');assert.deepEqual(request.options.body.getAll('ids'),['1']);assert.equal(request.options.body.get('csrf_token'),'csrf');
    assert.equal(c.nodes.get('game-notification-count').textContent,'3');
    c.document.listeners.visibilitychange();await c.flush();assert.equal(c.requests.filter(r=>r.url==='/read').length,1);
});
test('loading the next list page also marks that page read',async()=>{
    const c=harness();await c.flush();c.root.open=true;c.root.listeners.toggle();await c.flush();
    c.nodes.get('game-notification-more').listeners.click();await c.flush();assert.equal(c.requests.filter(r=>r.url==='/read').length,2);
    assert.ok(c.requests.some(r=>r.url.includes('page=2')));
});
