/* Radary (11 Nov 2026): ikona na mapach obrony i wojny, okrąg zasięgu po najechaniu, budowa we własnym regionie,
   rozbudowa do poziomu III, likwidacja (zwrot: 1 chip natsytowy, 20 żelaza) i obrona przeciwrakietowa radaru.
   Lokalizacji radaru nie można zmienić. Moduł korzysta z API mapy wystawionego przez game_military.js (window.GameRadar.init). */
(() => {
    'use strict';
    let api=null,cfg=null,layer=null,rangeCircle=null;
    const ROMAN=['','I','II','III'];
    const rc=()=>cfg.radar||{};
    const money=value=>api.number(Math.round(Number(value)||0))+' ROI';
    const uuid=()=>crypto.randomUUID?crypto.randomUUID():'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g,c=>{const r=crypto.getRandomValues(new Uint8Array(1))[0]&15;return (c==='x'?r:(r&3)|8).toString(16);});
    const radars=()=>cfg.radars||[];
    const visible=()=>api.mapFilters.has('radars');

    async function send(payload,regionId){
        const response=await fetch(rc().url,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':cfg.csrf},body:JSON.stringify(payload)});
        const result=await response.json().catch(()=>({}));
        if(!response.ok)throw new Error(result.error||'Nie udało się zapisać zmian.');
        try{sessionStorage.setItem('military-selected',String(regionId));sessionStorage.setItem('military-radar-message',result.message||'Zapisano.');}catch{}
        window.GameMilitaryMap?.saveView();location.reload();
    }
    function costRows(rule,parent){
        const rows=[[rc().chipIcon,`Chip natsytowy: ${rule.chips} (w magazynie: ${api.number(rc().chips||0)})`,(rc().chips||0)>=rule.chips],
                    [rc().ironIcon,`Żelazo: ${rule.iron} (w magazynie: ${api.number(rc().iron||0)})`,(rc().iron||0)>=rule.iron]];
        const list=api.make('div',null,'military-radar-costs');
        for(const [src,text,enough] of rows){const row=api.make('div',null,'military-radar-cost'+(enough?'':' military-range-error'));const icon=api.image(src);icon.width=22;icon.height=22;row.append(icon,api.make('span',text));list.append(row);}
        list.append(api.make('div',`Koszt: ${money(rule.cost)} z budżetu sił zbrojnych.`,'military-radar-cost military-radar-money'));
        parent.append(list);
        return rows.every(row=>row[2]);
    }
    function showRange(radar){
        hideRange();
        if(!radar.health)return;
        rangeCircle=L.circle([radar.position[1],radar.position[0]],{radius:radar.rangeKm/cfg.kmPerUnit,color:'#1e88e5',weight:2,dashArray:'6 6',fillColor:'#1e88e5',fillOpacity:.08,interactive:false}).addTo(api.map);
    }
    function hideRange(){if(rangeCircle){rangeCircle.remove();rangeCircle=null;}}

    function draw(){
        if(!layer)return;layer.clearLayers();hideRange();
        if(!visible())return;
        for(const radar of radars()){
            if(cfg.mode==='defense'&&radar.countryId!==cfg.countryId)continue;
            if(!radar.health)continue;   // 22 Nov 2026: zniszczony radar znika z mapy (likwidacja nadal w panelu regionu)
            const symbol=api.make('div',null,'military-radar-symbol military-map-badge'+(radar.health?'':' military-radar-destroyed'));
            if(cfg.mode==='defense'&&api.mapFilters.has('defenses')&&(cfg.defenses||[]).some(item=>item.targetKind==='radar'&&item.targetId===radar.id))symbol.classList.add('military-object-protected');
            symbol.append(api.image(cfg.radarIcon,'Radar'),api.make('span',ROMAN[radar.level],'military-radar-level'));
            if(radar.countryId!==cfg.countryId){const flag=api.image(cfg.flags[String(radar.countryId)]||'','');flag.className='military-radar-flag';flag.onerror=()=>flag.remove();symbol.append(flag);}
            const life=api.make('progress');life.className='map-health-bar';life.max=100;life.value=radar.health;window.GameHealth?.paint(life,radar.health);symbol.append(life);
            const tooltip=api.make('div');tooltip.append(api.make('strong',`${radar.name} · poziom ${ROMAN[radar.level]}`),api.healthBar(radar.health),
                api.make('p',radar.health?`Zasięg wykrywania: ${api.number(radar.rangeKm)} km`:'Radar zniszczony — nie wykrywa obiektów.'));
            const marker=api.bindObjectTooltip(L.marker([radar.position[1],radar.position[0]],{icon:L.divIcon({html:symbol,className:'military-map-marker',iconSize:[28,28],iconAnchor:[14,14]}),zIndexOffset:1650}),tooltip);
            marker.on('mouseover',()=>showRange(radar));marker.on('mouseout',hideRange);
            marker.on('click',()=>{
                if(api.busy())return;
                if(cfg.mode==='defense'){if(radar.countryId===cfg.countryId)api.selectObject('radar',{...radar,regionId:radar.regionId});return;}
                if(radar.countryId===cfg.countryId)return;
                if(!radar.health){api.feedback('Radar został zniszczony.');return;}
                api.showRegion(radar.regionId,null,{kind:'radar',id:radar.id,countryId:radar.countryId,name:radar.name,point:radar.position,health:radar.health});
            });
            marker.addTo(layer);
        }
    }

    // ---------- panel regionu (obrona państwa) ----------
    function regionPanel(regionId,actions,list){
        if(!api||cfg.mode!=='defense')return;
        const build=api.button('Zbuduj radar',()=>buildModal(regionId),actions,cfg.radarIcon);
        if(!rc().researched){build.disabled=true;build.title='Wymagana technologia: Rozpoznanie radarowe (Badania i rozwój).';}
        api.lockButton(build);
        for(const radar of radars().filter(r=>r.countryId===cfg.countryId&&String(r.regionId)===String(regionId))){
            const card=api.make('section',null,'military-base military-radar-card');card.id=`military-radar-${radar.id}`;
            const title=api.make('h3',`${radar.name} · poziom ${ROMAN[radar.level]} / III`);title.prepend(api.image(cfg.radarIcon));card.append(title,api.healthBar(radar.health));
            card.append(api.make('p',radar.health?`Zasięg wykrywania obcych rakiet i samolotów: ${api.number(radar.rangeKm)} km.`:'Radar zniszczony — nie wykrywa obiektów. Możesz go zlikwidować.'));
            if(radar.health>0)api.defenseActions('radar',radar.id,card);
            if(radar.upgrade){const up=api.button(`Rozbuduj do poziomu ${ROMAN[radar.upgrade.level]}`,()=>upgradeModal(radar),card,cfg.radarIcon);if(!radar.health){up.disabled=true;up.title='Zniszczonego radaru nie można rozbudować.';}api.lockButton(up);}
            api.button('Pokaż radar',()=>{api.map.setView([radar.position[1],radar.position[0]],Math.max(api.map.getZoom(),3));showRange(radar);},card,cfg.radarIcon);
            api.button('Zlikwiduj radar',()=>api.modal('Zlikwidować radar?',()=>{
                api.fields.append(api.make('p',`${radar.name} zniknie z mapy.`),api.make('p','Do magazynu wróci 1 chip natsytowy i 20 żelaza (0 ROI), niezależnie od poziomu radaru. Obrona przeciwrakietowa radaru zostanie usunięta.'));
            },()=>send({action:'liquidate',radar_id:radar.id},regionId)),card);
            card.append(api.make('p','Lokalizacji radaru nie można zmienić.','land-muted'));
            list.append(card);
        }
    }
    function buildModal(regionId){
        const rule=rc().levels[1];
        api.modal('Budowa radaru — poziom I',()=>{
            api.fields.append(api.make('p',`Zasięg wykrywania: ${api.number(rule.rangeKm)} km (poziom II: ${api.number(rc().levels[2].rangeKm)} km, poziom III: ${api.number(rc().levels[3].rangeKm)} km).`));
            const enough=costRows(rule,api.fields);
            api.fields.append(api.make('p','Po zatwierdzeniu wskaż na mapie miejsce w regionie. Lokalizacji radaru nie będzie można później zmienić.','land-muted'));
            if(!enough)document.getElementById('military-dialog-confirm').disabled=true;
        },async()=>{api.dialog.close();api.startLocation({id:'radar',kind:'radar',regionId:String(regionId)});});
    }
    function upgradeModal(radar){
        const rule=radar.upgrade;
        api.modal(`Rozbudowa radaru — poziom ${ROMAN[rule.level]}`,()=>{
            api.fields.append(api.make('p',`Zasięg wykrywania wzrośnie z ${api.number(radar.rangeKm)} km do ${api.number(rule.rangeKm)} km.`));
            if(!costRows(rule,api.fields))document.getElementById('military-dialog-confirm').disabled=true;
        },()=>send({action:'upgrade',radar_id:radar.id},radar.regionId));
    }
    async function place(target,point){
        await send({action:'build',region_id:Number(target.regionId),x:point.lng,y:point.lat,request_id:target.requestId||(target.requestId=uuid())},target.regionId);
    }

    window.GameRadar={
        init(context){
            api=context;cfg=context.config;
            try{const message=sessionStorage.getItem('military-radar-message');if(message){sessionStorage.removeItem('military-radar-message');api.feedback(message);}}catch{}
        },
        attach(map){if(!api)return;api.map=map;layer=L.layerGroup().addTo(map);draw();},
        update(state){if(!api||!layer)return;cfg.radars=state.radars||cfg.radars;draw();},
        draw,regionPanel,place,
    };
})();
