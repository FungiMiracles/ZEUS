(() => {
    'use strict';
    const node=document.getElementById('intelligence-config');if(!node)return;
    const config=JSON.parse(node.textContent),number=value=>new Intl.NumberFormat('pl-PL').format(value);
    const make=(tag,text)=>{const node=document.createElement(tag);if(text!=null)node.textContent=text;return node;};
    const country=document.getElementById('intel-country');
    let regionLayer,countryLayer;
    const countryMode=()=>kind.value==='warehouses';
    const region=document.getElementById('intel-region'),agent=document.getElementById('intel-agent'),kind=document.getElementById('intel-kind');
    const recruit=document.getElementById('intel-recruit'),mission=document.getElementById('intel-mission'),level=document.getElementById('intel-level');
    const confirm=document.getElementById('intel-confirm'),confirmButton=document.getElementById('intel-confirm-submit');
    let state=config,anchor=Date.parse(state.gameNow),realAnchor=performance.now(),pending=null,refreshing=false;
    function id(){return crypto.randomUUID?crypto.randomUUID():'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g,c=>{const r=crypto.getRandomValues(new Uint8Array(1))[0]&15;return(c==='x'?r:r&3|8).toString(16);});}
    for(let i=1;i<=7;i++){const option=make('option',`Poziom ${i} — szansa ${config.agentChances[i-1]}% — ${number(config.agentCosts[i-1])} ROI`);option.value=i;level.append(option);}
    for(const [id,item] of Object.entries(config.regions)){if(item.countryId===config.countryId||!item.countryId)continue;const option=make('option',`${item.name} — ${config.countries[String(item.countryId)]||''}`);option.value=id;region.append(option);}
    for(const [code,label] of Object.entries(config.missionTypes)){const option=make('option',label);option.value=code;kind.append(option);}
    for(const target of new Set(Object.values(config.regions).map(item=>item.countryId).filter(id=>id&&id!==config.countryId))){const option=make('option',config.countries[String(target)]);option.value=target;country.append(option);}
    function updateCost(){document.getElementById('intel-recruit-cost').textContent='Koszt rekrutacji: '+number(config.agentCosts[Number(level.value)-1]*Number(recruit.elements.count.value||0))+' ROI';}
    recruit.oninput=updateCost;updateCost();
    function updateTarget(){const target=config.regions[region.value];document.getElementById('intel-target').textContent=countryMode()?(country.value?'Cel: całe państwo — '+config.countries[country.value]:'Wybierz całe państwo na mapie.'):target?'Cel: '+target.name+' — '+config.countries[String(target.countryId)]:'';updateMapTargets();}
    function updateQuote(){const selected=state.agents.find(item=>item.id===Number(agent.value));document.getElementById('intel-mission-quote').textContent=`Czas: ${config.missionDays[kind.value]} dni Entendy. `+(selected?`Koszt misji agenta poziomu ${selected.level}: ${number(config.missionCosts[selected.level-1])} ROI.`:'Wybierz agenta, aby zobaczyć koszt misji.');}
    function updateMode(){const whole=countryMode();region.disabled=whole;region.required=!whole;country.disabled=!whole;country.required=whole;document.getElementById('intel-region-label').hidden=whole;document.getElementById('intel-country-label').hidden=!whole;updateTarget();updateQuote();}
    region.onchange=updateTarget;country.onchange=updateTarget;kind.onchange=updateMode;agent.onchange=updateQuote;
    function ask(title,text,payload){document.getElementById('intel-agent-name-label').hidden=true;document.getElementById('intel-confirm-icon').hidden=!['recruit','rename'].includes(payload.action);pending={...payload,request_id:id()};document.getElementById('intel-confirm-title').textContent=title;document.getElementById('intel-confirm-text').textContent=text;document.getElementById('intel-confirm-error').textContent='';confirm.showModal();}
    document.getElementById('intel-confirm-cancel').onclick=()=>confirm.close();
    confirmButton.onclick=async()=>{
        if(!pending)return;if(pending.action==='rename')pending.name=document.getElementById('intel-agent-name').value;confirmButton.disabled=true;
        try{const response=await fetch(config.changeUrl,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':config.csrf},body:JSON.stringify(pending)});const result=await response.json();if(!response.ok)throw new Error(result.error||'Nie udało się zapisać operacji.');confirm.close();pending=null;await refresh();}
        catch(error){document.getElementById('intel-confirm-error').textContent=error.message;}finally{confirmButton.disabled=false;}
    };
    recruit.onsubmit=event=>{event.preventDefault();const count=Number(recruit.elements.count.value),selected=Number(level.value);ask('Rekrutacja agentów',`Agenci: ${count}, poziom ${selected}. Koszt: ${number(config.agentCosts[selected-1]*count)} ROI z budżetu służb.`,{action:'recruit',level:selected,count});};
    mission.onsubmit=event=>{event.preventDefault();const selected=state.agents.find(item=>item.id===Number(agent.value));if(!selected)return;const target=countryMode()?config.countries[country.value]:config.regions[region.value]?.name;ask('Rozpocząć misję?',`${config.missionTypes[kind.value]} — ${target}. Koszt: ${number(config.missionCosts[selected.level-1])} ROI. Czas: ${config.missionDays[kind.value]} dni Entendy.`,{action:'mission',...(countryMode()?{country_id:Number(country.value)}:{region_id:Number(region.value)}),agent_id:selected.id,kind:kind.value});};
    document.getElementById('intel-counter-upgrade').onclick=()=>ask('Wzmocnić kontrwywiad?',`Poziom ${state.counterLevel+1}. Koszt: ${number(state.counterCost)} ROI z budżetu służb.`,{action:'counter_upgrade',expected_level:state.counterLevel});
    async function showReport(id){try{const response=await fetch(config.reportUrl.replace(/0$/,id),{credentials:'same-origin',cache:'no-store'});const result=await response.json();if(!response.ok)throw new Error(result.error||'Raport niedostępny.');window.showIntelligenceReport(result.report);}catch(error){document.getElementById('intel-error').textContent=error.message;}}
    function agentName(tag,name){const heading=make(tag,name);heading.className='intel-agent-name';const icon=make('img');icon.src=config.agentIcon;icon.alt='';heading.prepend(icon);return heading;}
    // 12 Nov 2026: ikona agenta z paskiem postępu na każdym regionie z trwającą misją.
    let missionLayer=null;const regionCenters=new Map(),countryCenters=new Map();
    function drawMissionMarkers(){
        if(!missionLayer)return;missionLayer.clearLayers();
        const byRegion=new Map();for(const item of state.missions){if(item.completed)continue;const key=item.scope==='country'?'country:'+item.countryId:item.regionId;if(!key)continue;if(!byRegion.has(key))byRegion.set(key,[]);byRegion.get(key).push(item);}
        for(const [regionId,items] of byRegion){
            const center=regionId.startsWith('country:')?countryCenters.get(regionId.slice(8)):regionCenters.get(regionId);if(!center)continue;
            const box=make('div');box.className='intel-map-agent';const icon=make('img');icon.src=config.agentIcon;icon.alt='';box.append(icon);
            for(const item of items){const bar=make('progress');bar.className='intel-map-progress';bar.max=100;bar.dataset.starts=item.startsAt;bar.dataset.ends=item.endsAt;bar.setAttribute('aria-label','Postęp misji: '+item.kind);box.append(bar);}
            const marker=L.marker(center,{icon:L.divIcon({html:box,className:'intel-map-agent-marker',iconSize:[34,30+6*items.length],iconAnchor:[17,15]}),keyboard:false});
            marker.bindTooltip(make('span',items.map(item=>`${item.agentName}: ${item.kind} — ${item.region}`).join(' · ')),{direction:'top'});
            marker.addTo(missionLayer);
        }
        updateProgress();
    }
    function render(){
        {const funds=document.getElementById('module-funds-available');if(funds){const full=funds.querySelector('.module-funds-full'),mld=funds.querySelector('.module-funds-mld');const text=window.GameMoney?window.GameMoney.format(state.budgetAvailable):number(state.budgetAvailable)+' ROI';if(full&&mld&&window.GameMoney){full.textContent=text;mld.firstChild.nodeValue=window.GameMoney.billions(state.budgetAvailable)+' ';}else funds.textContent=text;}}
        document.getElementById('intel-counter').textContent=`Poziom ${state.counterLevel}/7. Zmniejszenie szans obcych agentów o ${state.protection}% proporcjonalnie.`;
        {const box=document.getElementById('intel-sabotage');if(box){box.replaceChildren();const items=state.sabotageAgainstUs||[];
            for(const item of items){const card=make('div');card.className='intel-card '+(item.success?'is-failed':'is-success');
                card.append(make('h3',`${item.kind} — ${item.region}`),make('p',`${item.date} · ${item.success?'sabotaż udany':'próba nieudana'}${item.captured?' · schwytano agenta':''}`),make('p',item.culprit?`Sprawca: ${item.culprit}`:'Sprawca nieustalony'));box.append(card);}
            if(!items.length)box.append(make('p','Brak wykrytych prób sabotażu.'));
            collapse(box,[...box.querySelectorAll(':scope>.intel-card')],4,'sabotage','wykrytych prób');}}
        const upgrade=document.getElementById('intel-counter-upgrade');upgrade.disabled=state.counterLevel>=7;upgrade.textContent=state.counterLevel>=7?'Maksymalny poziom':`Wzmocnij ochronę — ${number(state.counterCost)} ROI`;
        const selected=agent.value;agent.replaceChildren();const agentList=document.getElementById('intel-agents');agentList.replaceChildren();
        for(const item of state.agents){const card=make('div');card.className='intel-card'+(item.captured?' is-captured':item.busy?' is-busy':'');card.append(agentName('h3',item.name),make('p',`Poziom ${item.level} · szansa ${item.chance}% · ${item.captured?'schwytany — niedostępny':item.busy?'na misji':'dostępny'}`));
            const rename=make('button','Zmień imię i nazwisko');rename.type='button';rename.onclick=()=>{ask('Imię i nazwisko agenta','Zmiana nazwy nie wpływa na poziom ani trwającą misję.',{action:'rename',agent_id:item.id});document.getElementById('intel-agent-name-label').hidden=false;const input=document.getElementById('intel-agent-name');input.value=item.name.startsWith('Agent #')?'':item.name;input.focus();};card.append(rename);
            const active=state.missions.find(m=>m.agentId===item.id&&!m.completed);if(active){card.append(make('p',`${active.country} · ${active.region}`),make('p',active.kind));appendMissionTime(card,active);}
            agentList.append(card);if(!item.busy&&!item.captured){const option=make('option',`${item.name} — poziom ${item.level} (${item.chance}%)`);option.value=item.id;agent.append(option);}}
        if([...agent.options].some(option=>option.value===selected))agent.value=selected;
        if(!state.agents.length)agentList.append(make('p','Nie zrekrutowano jeszcze agentów.'));
        collapse(agentList,[...agentList.querySelectorAll(':scope>.intel-card')],8,'agents','agentów');
        document.getElementById('intel-send').disabled=!agent.options.length;
        const list=document.getElementById('intel-missions');list.replaceChildren();
        const missionOrder=[...state.missions.filter(m=>!m.completed),...state.missions.filter(m=>m.completed)];
        for(const item of missionOrder){const card=make('section');card.className='intel-card'+(!item.completed?' is-busy':item.success?' is-success':' is-failed');card.append(make('h3',`${item.kind} — ${item.region}`),agentName('p',`${item.agentName} · ${item.country}`));
            if(item.completed){card.append(make('p',item.success?'Misja zakończona powodzeniem.':item.captured?'Misja nie powiodła się. Agent schwytany — nie wraca.':'Misja nie powiodła się. Agent jest dostępny.'));const button=make('button','Otwórz raport');button.type='button';button.onclick=()=>showReport(item.id);card.append(button);}
            else appendMissionTime(card,item);
            list.append(card);
        }
        if(!state.missions.length)list.append(make('p','Brak misji.'));
        collapse(list,[...list.querySelectorAll(':scope>.intel-card')],state.missions.filter(m=>!m.completed).length+6,'missions','misji');
        renderResources();
        updateQuote();updateProgress();drawMissionMarkers();
    }
    // 21 Nov 2026: rozpoznane zasoby regionów — ważne 180 dni Entendy (także na mapie wywiadu i mapie kopalń)
    function renderResources(){
        const box=document.getElementById('intel-resources');if(!box)return;box.replaceChildren();
        for(const item of state.resourceReports||[]){
            const card=make('section');card.className='intel-card is-success intel-resource-card';
            card.append(make('h3',`${item.region} — ${item.country}`),make('p',`Rozpoznanie: ${item.date} · dane ważne do ${item.until} (Entenda)`));
            const list=make('dl');list.className='intel-resource-list';
            for(const entry of item.entries){const row=make('div');row.append(make('dt',entry.label),make('dd',entry.value));list.append(row);}
            card.append(list);box.append(card);
        }
        if(!(state.resourceReports||[]).length)box.append(make('p','Brak aktualnych danych o zasobach. Wyślij agenta z misją „Zasoby naturalne regionu”.'));
        else collapse(box,[...box.querySelectorAll(':scope>.intel-card')],6,'resources','raportów');
    }
    function resourceTip(id,text){
        const report=(state.resourceReports||[]).find(item=>item.regionId===id),box=make('div');box.append(make('strong',text));
        if(report){box.append(make('div',`Zasoby (ważne do ${report.until}):`));for(const entry of report.entries)box.append(make('div',`${entry.label}: ${entry.value}`));}
        return box;
    }
    // 13 Nov 2026: długie listy agentów i misji zwinięte do najważniejszych pozycji (wygodne przewijanie, także na telefonie)
    const expanded={agents:false,missions:false,resources:false,sabotage:false};
    function collapse(container,cards,limit,key,noun){
        container.classList.toggle('intel-collapsed',!expanded[key]);
        if(cards.length<=limit)return;
        cards.slice(limit).forEach(card=>card.classList.add('intel-extra'));
        const more=make('button',expanded[key]?`Zwiń listę ${noun}`:`Pokaż wszystkie (${cards.length}) — ukryto ${cards.length-limit}`);more.type='button';more.className='intel-more';more.setAttribute('aria-expanded',String(expanded[key]));
        more.onclick=()=>{expanded[key]=!expanded[key];container.classList.toggle('intel-collapsed',!expanded[key]);more.textContent=expanded[key]?`Zwiń listę ${noun}`:`Pokaż wszystkie (${cards.length}) — ukryto ${cards.length-limit}`;more.setAttribute('aria-expanded',String(expanded[key]));};
        container.append(more);
    }
    function appendMissionTime(card,item){card.append(make('p','Planowany koniec (Entenda): '+new Intl.DateTimeFormat('pl-PL',{timeZone:'UTC',dateStyle:'short',timeStyle:'short'}).format(new Date(item.endsAt))));const bar=make('progress');bar.max=100;bar.dataset.starts=item.startsAt;bar.dataset.ends=item.endsAt;bar.setAttribute('aria-label','Postęp misji');const left=make('p');left.dataset.missionEnds=item.endsAt;card.append(bar,left);}
    function updateProgress(){const now=anchor+(performance.now()-realAnchor)*state.timeMultiplier;for(const bar of document.querySelectorAll('.intel-card progress,.intel-map-progress'))bar.value=Math.max(0,Math.min(100,(now-Date.parse(bar.dataset.starts))/(Date.parse(bar.dataset.ends)-Date.parse(bar.dataset.starts))*100));for(const text of document.querySelectorAll('[data-mission-ends]')){const minutes=Math.max(0,Math.ceil((Date.parse(text.dataset.missionEnds)-now)/60000));text.textContent=minutes?`Pozostało: ${Math.floor(minutes/1440)} dni ${Math.floor(minutes%1440/60)} godz. ${minutes%60} min Entendy`:'Misja kończy się — oczekiwanie na meldunek.';}}
    async function refresh(){if(refreshing)return;refreshing=true;try{const response=await fetch(config.stateUrl,{credentials:'same-origin',cache:'no-store'});if(!response.ok)throw new Error('Nie udało się odświeżyć wywiadu.');state=await response.json();anchor=Date.parse(state.gameNow);realAnchor=performance.now();render();}catch(error){document.getElementById('intel-error').textContent=error.message;}finally{refreshing=false;}}
    updateMode();render();setInterval(()=>{if(!document.hidden)refresh();},10000);setInterval(updateProgress,1000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
    if(config.initialReport)showReport(config.initialReport);
    function countryStyle(id){return {color:'#7d9178',weight:.7,fillColor:String(id)===country.value?'#E8B65C':Number(id)===config.countryId?'#9fbf8f':'#c9d3c2',fillOpacity:1};}
    function updateMapTargets(){if(!regionLayer||!countryLayer)return;const visible=countryMode()?countryLayer:regionLayer,hidden=countryMode()?regionLayer:countryLayer;if(map.hasLayer(hidden))map.removeLayer(hidden);if(!map.hasLayer(visible))visible.addTo(map);countryLayer.setStyle(feature=>countryStyle(feature.properties.countryId));regionLayer.resetStyle();}
    if(!window.L){document.getElementById('intel-map-status').textContent='Mapa jest niedostępna. Wybierz region z listy.';return;}
    const map=L.map('intel-map',{crs:L.CRS.Simple,minZoom:-10,maxZoom:8,zoomSnap:.25,attributionControl:false});map.setView([0,0],0);
    fetch(config.regionsUrl).then(response=>{if(!response.ok)throw new Error();return response.json();}).then(data=>{
        const regionStyle=feature=>({color:'#7d9178',weight:.7,fillColor:String(feature.properties.region_id)===region.value?'#E8B65C':config.regions[String(feature.properties.region_id)].countryId===config.countryId?'#9fbf8f':'#c9d3c2',fillOpacity:1});
        const layer=regionLayer=L.geoJSON(data,{coordsToLatLng:point=>L.latLng(point[1],point[0]),filter:feature=>!!config.regions[String(feature.properties?.region_id)],style:regionStyle,
            onEachFeature:(feature,item)=>{const id=String(feature.properties.region_id),info=config.regions[id];item.bindTooltip(()=>resourceTip(id,info.name+' — '+(config.countries[String(info.countryId)]||'')),{sticky:true});item.on({mouseover:()=>item.setStyle({weight:2,color:'#1E3A5F',fillColor:'#D5E5C6'}),mouseout:()=>layer.resetStyle(item),click:()=>{if(info.countryId&&info.countryId!==config.countryId){region.value=id;updateTarget();}}});}});
        // Group all territory of a controller into one country feature; no regional targets in warehouse mode.
        const grouped=new Map();
        for(const feature of data.features){const owner=config.regions[String(feature.properties?.region_id)]?.countryId;if(!owner)continue;const polygons=feature.geometry?.type==='Polygon'?[feature.geometry.coordinates]:feature.geometry?.type==='MultiPolygon'?feature.geometry.coordinates:[];if(!grouped.has(owner))grouped.set(owner,[]);grouped.get(owner).push(...polygons);}
        countryLayer=L.geoJSON({type:'FeatureCollection',features:[...grouped].map(([id,coordinates])=>({type:'Feature',properties:{countryId:id},geometry:{type:'MultiPolygon',coordinates}}))},{coordsToLatLng:point=>L.latLng(point[1],point[0]),style:feature=>countryStyle(feature.properties.countryId),onEachFeature:(feature,item)=>{const id=String(feature.properties.countryId);item.bindTooltip(make('span',config.countries[id]||'Państwo'),{sticky:true});item.on({mouseover:()=>item.setStyle({weight:2,color:'#1E3A5F',fillColor:'#D5E5C6'}),mouseout:()=>countryLayer.resetStyle(item),click:()=>{if(Number(id)!==config.countryId){country.value=id;updateTarget();}}});}});
        countryLayer.eachLayer(item=>countryCenters.set(String(item.feature.properties.countryId),item.getBounds().getCenter()));
        updateMapTargets();
        layer.eachLayer(item=>{const id=String(item.feature.properties.region_id),bounds=regionCenters.get('b'+id);regionCenters.set('b'+id,bounds?bounds.extend(item.getBounds()):L.latLngBounds(item.getBounds().getSouthWest(),item.getBounds().getNorthEast()));});
        for(const [key,bounds] of [...regionCenters])if(key.startsWith('b')){regionCenters.set(key.slice(1),bounds.getCenter());regionCenters.delete(key);}
        missionLayer=L.layerGroup().addTo(map);drawMissionMarkers();
        if(layer.getBounds().isValid())map.fitBounds(layer.getBounds(),{padding:[20,20],maxZoom:4});
    }).catch(()=>document.getElementById('intel-map-status').textContent='Nie udało się wczytać mapy. Wybierz region z listy.');
    // 26 Nov 2026: satelity szpiegowskie — kliknięcie własnego satelity otwiera opcje misji w kole wokół niego
    window.GameSatellites?.attach(map,{mode:'intelligence',csrf:config.csrf});window.GameSatellites?.panel(document.getElementById('satellite-panel'));
    if(window.ResizeObserver)new ResizeObserver(()=>map.invalidateSize()).observe(map.getContainer());
})();
