(() => {
    'use strict';
    const node=document.getElementById('intelligence-config');if(!node)return;
    const config=JSON.parse(node.textContent),number=value=>new Intl.NumberFormat('pl-PL').format(value);
    const make=(tag,text)=>{const node=document.createElement(tag);if(text!=null)node.textContent=text;return node;};
    const region=document.getElementById('intel-region'),agent=document.getElementById('intel-agent'),kind=document.getElementById('intel-kind');
    const recruit=document.getElementById('intel-recruit'),mission=document.getElementById('intel-mission'),level=document.getElementById('intel-level');
    const confirm=document.getElementById('intel-confirm'),confirmButton=document.getElementById('intel-confirm-submit');
    let state=config,anchor=Date.parse(state.gameNow),realAnchor=performance.now(),pending=null,refreshing=false;
    function id(){return crypto.randomUUID?crypto.randomUUID():'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g,c=>{const r=crypto.getRandomValues(new Uint8Array(1))[0]&15;return(c==='x'?r:r&3|8).toString(16);});}
    for(let i=1;i<=7;i++){const option=make('option',`Poziom ${i} — szansa ${config.agentChances[i-1]}% — ${number(config.agentCosts[i-1])} ROI`);option.value=i;level.append(option);}
    for(const [id,item] of Object.entries(config.regions)){if(item.countryId===config.countryId||!item.countryId)continue;const option=make('option',`${item.name} — ${config.countries[String(item.countryId)]||''}`);option.value=id;region.append(option);}
    for(const [code,label] of Object.entries(config.missionTypes)){const option=make('option',label);option.value=code;kind.append(option);}
    const unavailable=make('option','Stany magazynowe regionu — niedostępne');unavailable.disabled=true;kind.append(unavailable);
    function updateCost(){document.getElementById('intel-recruit-cost').textContent='Koszt rekrutacji: '+number(config.agentCosts[Number(level.value)-1]*Number(recruit.elements.count.value||0))+' ROI';}
    recruit.oninput=updateCost;updateCost();
    function updateTarget(){const target=config.regions[region.value];document.getElementById('intel-target').textContent=target?'Cel: '+target.name+' — '+config.countries[String(target.countryId)]:'';}
    region.onchange=updateTarget;
    function ask(title,text,payload){document.getElementById('intel-agent-name-label').hidden=true;document.getElementById('intel-confirm-icon').hidden=!['recruit','rename'].includes(payload.action);pending={...payload,request_id:id()};document.getElementById('intel-confirm-title').textContent=title;document.getElementById('intel-confirm-text').textContent=text;document.getElementById('intel-confirm-error').textContent='';confirm.showModal();}
    document.getElementById('intel-confirm-cancel').onclick=()=>confirm.close();
    confirmButton.onclick=async()=>{
        if(!pending)return;if(pending.action==='rename')pending.name=document.getElementById('intel-agent-name').value;confirmButton.disabled=true;
        try{const response=await fetch(config.changeUrl,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':config.csrf},body:JSON.stringify(pending)});const result=await response.json();if(!response.ok)throw new Error(result.error||'Nie udało się zapisać operacji.');confirm.close();pending=null;await refresh();}
        catch(error){document.getElementById('intel-confirm-error').textContent=error.message;}finally{confirmButton.disabled=false;}
    };
    recruit.onsubmit=event=>{event.preventDefault();const count=Number(recruit.elements.count.value),selected=Number(level.value);ask('Rekrutacja agentów',`Agenci: ${count}, poziom ${selected}. Koszt: ${number(config.agentCosts[selected-1]*count)} ROI z budżetu służb.`,{action:'recruit',level:selected,count});};
    mission.onsubmit=event=>{event.preventDefault();ask('Rozpocząć misję?',`${config.missionTypes[kind.value]} — ${config.regions[region.value]?.name}. Koszt: 3 mld ROI. Czas: 7 dni Entendy.`,{action:'mission',region_id:Number(region.value),agent_id:Number(agent.value),kind:kind.value});};
    document.getElementById('intel-counter-upgrade').onclick=()=>ask('Wzmocnić kontrwywiad?',`Poziom ${state.counterLevel+1}. Koszt: ${number(state.counterCost)} ROI z budżetu służb.`,{action:'counter_upgrade',expected_level:state.counterLevel});
    async function showReport(id){try{const response=await fetch(config.reportUrl.replace(/0$/,id),{credentials:'same-origin',cache:'no-store'});const result=await response.json();if(!response.ok)throw new Error(result.error||'Raport niedostępny.');window.showIntelligenceReport(result.report);}catch(error){document.getElementById('intel-error').textContent=error.message;}}
    function agentName(tag,name){const heading=make(tag,name);heading.className='intel-agent-name';const icon=make('img');icon.src=config.agentIcon;icon.alt='';heading.prepend(icon);return heading;}
    // 12 Nov 2026: ikona agenta z paskiem postępu na każdym regionie z trwającą misją.
    let missionLayer=null;const regionCenters=new Map();
    function drawMissionMarkers(){
        if(!missionLayer)return;missionLayer.clearLayers();
        const byRegion=new Map();for(const item of state.missions){if(item.completed||!item.regionId)continue;if(!byRegion.has(item.regionId))byRegion.set(item.regionId,[]);byRegion.get(item.regionId).push(item);}
        for(const [regionId,items] of byRegion){
            const center=regionCenters.get(regionId);if(!center)continue;
            const box=make('div');box.className='intel-map-agent';const icon=make('img');icon.src=config.agentIcon;icon.alt='';box.append(icon);
            for(const item of items){const bar=make('progress');bar.className='intel-map-progress';bar.max=100;bar.dataset.starts=item.startsAt;bar.dataset.ends=item.endsAt;bar.setAttribute('aria-label','Postęp misji: '+item.kind);box.append(bar);}
            const marker=L.marker(center,{icon:L.divIcon({html:box,className:'intel-map-agent-marker',iconSize:[34,30+6*items.length],iconAnchor:[17,15]}),keyboard:false});
            marker.bindTooltip(make('span',items.map(item=>`${item.agentName}: ${item.kind} — ${item.region}`).join(' · ')),{direction:'top'});
            marker.addTo(missionLayer);
        }
        updateProgress();
    }
    function render(){
        {const funds=document.getElementById('module-funds-available');if(funds)funds.textContent=window.GameMoney?window.GameMoney.format(state.budgetAvailable):number(state.budgetAvailable)+' ROI';}
        document.getElementById('intel-counter').textContent=`Poziom ${state.counterLevel}/7. Zmniejszenie szans obcych agentów o ${state.protection}% proporcjonalnie.`;
        const upgrade=document.getElementById('intel-counter-upgrade');upgrade.disabled=state.counterLevel>=7;upgrade.textContent=state.counterLevel>=7?'Maksymalny poziom':`Wzmocnij ochronę — ${number(state.counterCost)} ROI`;
        const selected=agent.value;agent.replaceChildren();const agentList=document.getElementById('intel-agents');agentList.replaceChildren();
        for(const item of state.agents){const card=make('div');card.className='intel-card';card.append(agentName('h3',item.name),make('p',`Poziom ${item.level} · szansa ${item.chance}% · ${item.captured?'schwytany — niedostępny':item.busy?'na misji':'dostępny'}`));
            const rename=make('button','Zmień imię i nazwisko');rename.type='button';rename.onclick=()=>{ask('Imię i nazwisko agenta','Zmiana nazwy nie wpływa na poziom ani trwającą misję.',{action:'rename',agent_id:item.id});document.getElementById('intel-agent-name-label').hidden=false;const input=document.getElementById('intel-agent-name');input.value=item.name.startsWith('Agent #')?'':item.name;input.focus();};card.append(rename);
            const active=state.missions.find(m=>m.agentId===item.id&&!m.completed);if(active){card.append(make('p',`${active.country} · ${active.region}`),make('p',active.kind));appendMissionTime(card,active);}
            agentList.append(card);if(!item.busy&&!item.captured){const option=make('option',`${item.name} — poziom ${item.level} (${item.chance}%)`);option.value=item.id;agent.append(option);}}
        if([...agent.options].some(option=>option.value===selected))agent.value=selected;
        if(!state.agents.length)agentList.append(make('p','Nie zrekrutowano jeszcze agentów.'));
        document.getElementById('intel-send').disabled=!agent.options.length;
        const list=document.getElementById('intel-missions');list.replaceChildren();
        for(const item of state.missions){const card=make('section');card.className='intel-card';card.append(make('h3',`${item.kind} — ${item.region}`),agentName('p',`${item.agentName} · ${item.country}`));
            if(item.completed){card.append(make('p',item.success?'Misja zakończona powodzeniem.':item.captured?'Misja nie powiodła się. Agent schwytany — nie wraca.':'Misja nie powiodła się. Agent jest dostępny.'));const button=make('button','Otwórz raport');button.type='button';button.onclick=()=>showReport(item.id);card.append(button);}
            else appendMissionTime(card,item);
            list.append(card);
        }
        if(!state.missions.length)list.append(make('p','Brak misji.'));updateProgress();drawMissionMarkers();
    }
    function appendMissionTime(card,item){card.append(make('p','Planowany koniec (Entenda): '+new Intl.DateTimeFormat('pl-PL',{timeZone:'UTC',dateStyle:'short',timeStyle:'short'}).format(new Date(item.endsAt))));const bar=make('progress');bar.max=100;bar.dataset.starts=item.startsAt;bar.dataset.ends=item.endsAt;bar.setAttribute('aria-label','Postęp misji');const left=make('p');left.dataset.missionEnds=item.endsAt;card.append(bar,left);}
    function updateProgress(){const now=anchor+(performance.now()-realAnchor)*state.timeMultiplier;for(const bar of document.querySelectorAll('.intel-card progress,.intel-map-progress'))bar.value=Math.max(0,Math.min(100,(now-Date.parse(bar.dataset.starts))/(Date.parse(bar.dataset.ends)-Date.parse(bar.dataset.starts))*100));for(const text of document.querySelectorAll('[data-mission-ends]')){const minutes=Math.max(0,Math.ceil((Date.parse(text.dataset.missionEnds)-now)/60000));text.textContent=minutes?`Pozostało: ${Math.floor(minutes/1440)} dni ${Math.floor(minutes%1440/60)} godz. ${minutes%60} min Entendy`:'Misja kończy się — oczekiwanie na meldunek.';}}
    async function refresh(){if(refreshing)return;refreshing=true;try{const response=await fetch(config.stateUrl,{credentials:'same-origin',cache:'no-store'});if(!response.ok)throw new Error('Nie udało się odświeżyć wywiadu.');state=await response.json();anchor=Date.parse(state.gameNow);realAnchor=performance.now();render();}catch(error){document.getElementById('intel-error').textContent=error.message;}finally{refreshing=false;}}
    render();setInterval(()=>{if(!document.hidden)refresh();},10000);setInterval(updateProgress,1000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
    if(config.initialReport)showReport(config.initialReport);
    if(!window.L){document.getElementById('intel-map-status').textContent='Mapa jest niedostępna. Wybierz region z listy.';return;}
    const map=L.map('intel-map',{crs:L.CRS.Simple,minZoom:-10,maxZoom:8,zoomSnap:.25,attributionControl:false});map.setView([0,0],0);
    fetch(config.regionsUrl).then(response=>{if(!response.ok)throw new Error();return response.json();}).then(data=>{
        const layer=L.geoJSON(data,{coordsToLatLng:point=>L.latLng(point[1],point[0]),filter:feature=>!!config.regions[String(feature.properties?.region_id)],
            style:feature=>({color:'#fff',weight:1,fillColor:config.regions[String(feature.properties.region_id)].countryId===config.countryId?'#779ce4':'#b7c8dd',fillOpacity:.85}),
            onEachFeature:(feature,item)=>{const id=String(feature.properties.region_id),info=config.regions[id];item.bindTooltip(make('span',info.name+' — '+(config.countries[String(info.countryId)]||'')),{sticky:true});item.on({mouseover:()=>item.setStyle({weight:3,color:'#244984'}),mouseout:()=>layer.resetStyle(item),click:()=>{if(info.countryId&&info.countryId!==config.countryId){region.value=id;updateTarget();}}});}}).addTo(map);
        layer.eachLayer(item=>{const id=String(item.feature.properties.region_id),bounds=regionCenters.get('b'+id);regionCenters.set('b'+id,bounds?bounds.extend(item.getBounds()):L.latLngBounds(item.getBounds().getSouthWest(),item.getBounds().getNorthEast()));});
        for(const [key,bounds] of [...regionCenters])if(key.startsWith('b')){regionCenters.set(key.slice(1),bounds.getCenter());regionCenters.delete(key);}
        missionLayer=L.layerGroup().addTo(map);drawMissionMarkers();
        if(layer.getBounds().isValid())map.fitBounds(layer.getBounds(),{padding:[20,20],maxZoom:4});
    }).catch(()=>document.getElementById('intel-map-status').textContent='Nie udało się wczytać mapy. Wybierz region z listy.');
    if(window.ResizeObserver)new ResizeObserver(()=>map.invalidateSize()).observe(map.getContainer());
})();
