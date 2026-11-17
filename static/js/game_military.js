(() => {
    'use strict';
    const element = document.getElementById('military-config');
    if (!element) return;
    const config = JSON.parse(element.textContent), own = id => Number(config.regions[id]?.countryId) === config.countryId;
    const warTheme=config.mode==='war';
    // 13 Nov 2026: mapa obrony w kolorystyce mapy świata (moduł „Świat”): granatowy ocean, zielony ląd, białe miasta.
    const DEF={enemy:'#d98b7a',land:'#c9d3c2',own:'#9fbf8f',border:'#667C63',regionBorder:'#7d9178',hover:'#D5E5C6',selected:'#1E3A5F',city:'#FFFFFF',cityBorder:'#22301f',ally:'#d6e6a6',permit:'#e6d27a',frozen:'#c9c39a'};
    const mobileLayout=()=>window.matchMedia('(max-width:900px)').matches;
    let regionLayerRef=null,highlightedRegion=null;
    const repaintRegions=()=>{if(regionLayerRef)regionLayerRef.eachLayer(layer=>{regionLayerRef.resetStyle(layer);if(String(layer.feature?.properties?.region_id)===highlightedRegion)layer.bringToFront();});};
    const smoothScroll=()=>matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth';
    const regionBounds=new Map();
    let focusedObject=null,framedRegion=null,activeObjectMarker=null;
    const mapFilterKinds=['air','naval','land','nuclear','defenses','mines','factories','power','radars','cities'];
    const mapFiltersKey=`military-map-filters:v3:${config.countryId}:${config.mode}`;
    function restoreMapFilters(){
        try{const saved=JSON.parse(sessionStorage.getItem(mapFiltersKey));if(Array.isArray(saved)&&saved.every(kind=>mapFilterKinds.includes(kind)))return new Set(saved);}catch{}
        // Filtry zapisane przed dodaniem miast (12 Nov 2026): zachowujemy je i pokazujemy miasta.
        try{const v2=JSON.parse(sessionStorage.getItem(`military-map-filters:v2:${config.countryId}:${config.mode}`));if(Array.isArray(v2)&&v2.every(kind=>mapFilterKinds.includes(kind)))return new Set([...v2,'cities']);}catch{}
        // Filters saved before radars existed (11 Nov 2026): keep them and show radars.
        try{const old=JSON.parse(sessionStorage.getItem(`military-map-filters:${config.countryId}:${config.mode}`));if(Array.isArray(old)&&old.every(kind=>mapFilterKinds.includes(kind)))return new Set([...old,'radars','cities']);}catch{}
        return new Set(mapFilterKinds);
    }
    const mapFilters=restoreMapFilters();
    function saveMapFilters(){try{sessionStorage.setItem(mapFiltersKey,JSON.stringify([...mapFilters]));}catch{}applyCityFilter();}
    function applyCityFilter(){const pane=map.getPane('militaryCities');if(pane)pane.style.display=mapFilters.has('cities')?'':'none';}  // wywoływane po utworzeniu mapy

    function updateReadiness(items=config.flights) {
        if(!warTheme){
            const counts={
                'defense-base-count':config.bases.length,
                'defense-map-base-count':config.bases.filter(base=>base.position).length,
                'defense-system-count':config.defenses.filter(defense=>defense.countryId===config.countryId).length,
                'defense-vessel-count':config.vessels.filter(vessel=>vessel.countryId===config.countryId).length
            };
            for(const [id,value] of Object.entries(counts)){const node=document.getElementById(id);if(node)node.textContent=value;}
            return;
        }
        document.getElementById('war-base-count').textContent=config.bases.length;
        document.getElementById('war-missile-count').textContent=new Intl.NumberFormat('pl-PL').format(
            Object.values(config.missiles).reduce((sum,item)=>sum+item.count,0));
        document.getElementById('war-flight-count').textContent=items.filter(item=>!item.radarOnly&&
            !item.returnedAt&&Date.parse(item.returnsAt||item.impactAt)>Date.parse(config.gameNow)).length;
    }
    updateReadiness();
    const metropolitan = new Set(config.metropolitanRegionIds);
    const number = value => new Intl.NumberFormat('pl-PL').format(value);
    const make = (tag, text, className) => { const node = document.createElement(tag); if (text != null) node.textContent = text; if (className) node.className = className; return node; };
    const image = (src, alt = '') => { const node = make('img'); node.src = src; node.alt = alt; return node; };
    const selector = document.getElementById('military-region-select'), actions = document.getElementById('military-region-actions'), bases = document.getElementById('military-bases');
    const dialog = document.getElementById('military-dialog'), form = document.getElementById('military-dialog-form'), fields = document.getElementById('military-dialog-fields');
    let selected, selectedCity=null, selectedTarget=null, coastCleanup=null, submit, locating=null, locatingLayer=null, regionGeometry=null, savingLocation=false, sailing=null, redirecting=null, selectedVessel=null;
    // 16 Nov 2026: bazy za granicą (w regionach z pozwoleniem) — zarządzanie jak w regionach własnych.
    const abroadBaseRegion=id=>!own(id)&&config.bases.some(base=>String(base.regionId)===String(id));
    const permitRegion=id=>config.allyRegions?.[String(id)]?.permit==='ACTIVE';
    const manageable=id=>own(id)||abroadBaseRegion(id)||permitRegion(id);
    for (const [id, region] of Object.entries(config.regions)) {
        if (config.mode === 'defense' && !manageable(id)) continue;
        const option = make('option', region.name + (config.mode === 'defense' && !own(id) ? ' (za granicą)' : '')); option.value = id; selector.append(option);
    }
    if (config.mode === 'defense') {
        document.getElementById('military-upkeep').textContent = number(config.upkeep) + ' ROI';
    }
    // 13 Nov 2026: ikona jednostki obok pól garnizonu w oknach budowy / reorganizacji bazy.
    const fieldIcon=name=>config.resources?.[name]?.icon||config.vesselIcons?.[name]||null;
    function input(label, name, value, max) {
        const row = make('label', null, 'military-field'), node = make('input');
        const icon=fieldIcon(name);
        if(icon){const img=make('img',null,'military-field-icon');img.src=icon;img.alt='';img.width=26;img.height=26;row.append(img);row.classList.add('has-icon');}
        row.append(make('span',label,'military-field-label')); node.name = name; node.type = 'number'; node.min = '0'; node.step = '1'; node.value = value;
        if (max != null) node.max = max;
        node.required = true; row.append(node); fields.append(row); return node;
    }
    function choose(label, name, options) {
        const row = make('label', label), node = make('select'); node.name = name;
        for (const [value, text] of options) { const option = make('option', text); option.value = value; node.append(option); }
        row.append(node); fields.append(row); return node;
    }
    function modal(title, build, handler) {
        dialog.classList.remove('military-object-selected');
        document.getElementById('military-dialog-title').textContent = title; fields.replaceChildren();
        document.getElementById('military-dialog-error').textContent = ''; document.getElementById('military-dialog-confirm').disabled=false; submit = handler; build(); dialog.showModal();
    }
    async function post(data) {
        const response = await fetch(config.changeUrl, {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json','X-CSRF-Token':config.csrf},body:JSON.stringify(data)});
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Nie udało się zapisać zmian.');
        if(data.action==='location')sessionStorage.removeItem('military-pending-location-'+config.countryId);
        sessionStorage.setItem('military-selected', selected); location.reload();
    }
    // Okupowany region (11 Nov 2026): właściciel nie może w nim budować — przyciski budowy są wyszarzone.
    let regionLocked=false;
    const LOCKED_TEXT='Region jest okupowany przez przeciwnika — nie można w nim nic budować.';
    function lockButton(node){if(regionLocked){node.disabled=true;node.title=LOCKED_TEXT;node.classList.add('military-action-locked');}return node;}
    function button(text, handler, parent, icon, attack = false) {
        const node = make('button', text, 'military-action' + (attack ? ' military-attack' : '')); node.type = 'button';
        if (icon) node.prepend(image(icon)); node.addEventListener('click', handler); parent.append(node); return node;
    }
    const baseName=base=>base.name || `${base.label} #${base.id}`;
    const baseIcon=base=>base.kind==='nuclear'?config.siloIcon:config.baseIcon;
    function fitRegion(id) {
        if(config.mode!=='defense'||locating||sailing)return;
        const bounds=regionBounds.get(String(id));
        if(bounds?.isValid()) {
            map.invalidateSize({pan:false});
            map.fitBounds(bounds,{padding:[12,12],animate:false});
        }
    }
    function deployDialog(id) {
        const region=config.regions[id], abroad=!own(id);
        const requestId=crypto.randomUUID();
        modal('Rozmieszczenie bazy — '+region.name+(abroad?' (terytorium sojusznika)':''),()=>{
            // 13 Nov 2026: bazy lądowe, morskie i powietrzne bez limitu z tabeli „wojsko” — ograniczeniem są surowce (receptura poniżej).
            const kind=choose('Rodzaj bazy','kind',Object.entries(config.inventory).filter(([code,item])=>(code!=='naval'||region.coastal)&&(!abroad||code!=='nuclear')&&(code!=='nuclear'||item.available>0)).map(([code,item])=>[code,item.label]));
            const recipe=make('div',null,'military-recipe');recipe.setAttribute('aria-live','polite');fields.append(recipe);
            function renderRecipe(){
                recipe.replaceChildren();const materials=config.baseMaterials?.[kind.value];
                const confirm=document.getElementById('military-dialog-confirm');
                if(!materials?.length){recipe.hidden=true;confirm.disabled=false;return;}
                recipe.hidden=false;
                const row=make('div',null,'military-recipe-row');row.setAttribute('role','img');
                const missing=materials.filter(item=>item.have<item.need);
                materials.forEach((item,index)=>{
                    if(index)row.append(make('span','+','military-recipe-sign'));
                    const cell=make('span',null,'military-recipe-item'+(item.have<item.need?' is-missing':''));cell.title=`${item.label}: potrzeba ${number(item.need)}, w magazynie ${number(item.have)}`;
                    cell.append(image(item.icon,item.label),make('span',number(item.need),'military-recipe-badge'));row.append(cell);
                });
                row.append(make('span','→','military-recipe-sign'));
                const target=make('span',null,'military-recipe-item military-recipe-target');target.append(image(config.baseIcon,config.inventory[kind.value]?.label||'Baza'));row.append(target);
                row.setAttribute('aria-label',`Koszt budowy: ${materials.map(item=>`${number(item.need)} ${item.label}`).join(' + ')}`);
                recipe.append(make('span','Surowce na budowę bazy','military-recipe-title'),row,
                    make('p',materials.map(item=>`${item.label}: w magazynie ${number(item.have)}`).join(' · '),missing.length?'military-recipe-stock is-missing':'military-recipe-stock'));
                if(missing.length)recipe.append(make('p','Za mało surowców w magazynie: '+missing.map(item=>`${item.label} (brakuje ${number(item.need-item.have)})`).join(', ')+'.','military-range-error'));
                confirm.disabled=missing.length>0;
            }
            const inventory=make('div');fields.append(inventory);
            function renderGarrison(){inventory.replaceChildren();const capacities=config.baseCapacities[kind.value]||{};for(const [resource,capacity] of Object.entries(capacities)){
                const available=config.availableGarrison[kind.value][resource],initial=resource==='soldiers'||resource==='warheads'?Math.min(1,available):0;
                const field=input(`${config.resources[resource].label} — dostępne ${number(available)}, pojemność ${number(capacity)}`,resource,initial,Math.min(capacity,available));
                if(resource==='soldiers'||resource==='warheads')field.min='1';inventory.append(field.closest('label'));
            }}kind.onchange=()=>{renderRecipe();renderGarrison();};renderRecipe();renderGarrison();fields.append(make('p','Uzupełnij żołnierzy i sprzęt. Po zatwierdzeniu wskażesz obowiązkowo lokalizację bazy na mapie.'+(abroad?' Utrzymanie bazy za granicą jest dwukrotnie droższe.':'')));
        },async data=>{
            const kind=data.get('kind'),garrison=Object.fromEntries(Object.keys(config.baseCapacities[kind]||{}).map(key=>[key,Number(data.get(key))]));
            const response=await fetch(config.changeUrl,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':config.csrf},body:JSON.stringify({action:'deploy',region_id:Number(id),kind,garrison,request_id:requestId})});
            const result=await response.json();if(!response.ok)throw Error(result.error||'Nie udało się rozmieścić bazy.');
            sessionStorage.setItem('military-pending-location-'+config.countryId,String(result.base_id));sessionStorage.setItem('military-selected',id);location.reload();
        });
    }
    // Telefon: po wyborze regionu na mapie przewiń do panelu zarządzania (powrót przyciskiem „↑ Mapa”).
    function markRegion(id){highlightedRegion=id?String(id):null;repaintRegions();}
    function revealManagement(){
        if(!mobileLayout())return;
        const target=document.querySelector('.military-sidebar');
        if(target)setTimeout(()=>target.scrollIntoView({behavior:smoothScroll(),block:'start'}),120);
    }
    const backToMap=document.getElementById('military-back-to-map');
    if(backToMap)backToMap.addEventListener('click',()=>document.querySelector('.war-map-panel')?.scrollIntoView({behavior:smoothScroll(),block:'start'}));
    function selectRegion(id) {
        if(config.mode==='defense'){highlightedRegion=id?String(id):null;repaintRegions();}
        focusedObject=id?{kind:'region',id:String(id)}:null;
        framedRegion=id?String(id):null;
        showRegion(String(id));
        fitRegion(id);
    }
    function highlightSelection(scroll=false) {
        if(config.mode!=='defense')return;
        document.querySelectorAll('.military-object-selected').forEach(node=>node.classList.remove('military-object-selected'));
        if(!focusedObject)return;
        const card=['region','city'].includes(focusedObject.kind)?actions:document.getElementById(`military-${focusedObject.kind}-${focusedObject.id}`);
        if(!card)return;
        card.classList.add('military-object-selected');
        if(card!==actions)card.parentElement.prepend(card);
        if(scroll)card.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'center'});
    }
    function selectObject(kind,item) {
        focusedObject={kind,id:item.id};
        framedRegion=null;
        showRegion(String(item.regionId),null,{kind,id:item.id,countryId:item.countryId,name:kind==='base'?baseName(item):item.name,point:item.position,health:item.health});
        highlightSelection(true);
    }
    function bindObjectTooltip(marker,content,options={}) {
        if(config.mode!=='defense')return marker.bindTooltip(content,options);
        marker.bindTooltip(content,{...options,className:'military-wrapping-tooltip',direction:'top',offset:[0,-32]});
        marker.on('tooltipopen',()=>{
            if(activeObjectMarker&&activeObjectMarker!==marker)activeObjectMarker.closeTooltip();
            activeObjectMarker=marker;
            const tooltip=marker.getTooltip(),node=tooltip.getElement(),object=marker.getElement();
            if(!node||!object)return;
            const box=object.getBoundingClientRect(),viewport=map.getContainer().getBoundingClientRect();
            const anchor=map.latLngToContainerPoint(marker.getLatLng());
            const top=box.top-viewport.top,bottom=box.bottom-viewport.top;
            const above=top>=node.offsetHeight+12;
            tooltip.options.direction=above?'top':'bottom';
            tooltip.options.offset=L.point(0,(above?top-10:bottom+10)-anchor.y);
            tooltip.setLatLng(marker.getLatLng());
        });
        marker.on('tooltipclose',()=>{if(activeObjectMarker===marker)activeObjectMarker=null;});
        marker.on('click',()=>marker.closeTooltip());
        return marker;
    }
    function showRegion(id, cityId=null, target=null) {
        selectedCity=cityId;selectedTarget=target;
        if(focusedObject&&focusedObject.kind==='region'&&String(focusedObject.id)!==String(id))focusedObject=null;
        regionLocked=!!window.GameLandWar?.regionOccupied(id);
        selected = id; selector.value = id; actions.replaceChildren(); actions.classList.remove('military-object-selected'); bases.replaceChildren();
        const region = config.regions[id];
        document.getElementById('military-region-name').textContent = selectedTarget ? (selectedTarget.kind==='vessel'?selectedTarget.name:`${selectedTarget.name} — ${region.name}`) : selectedCity ? `${config.cities[selectedCity].name} — ${region.name}` : region?.name || 'Wybierz region na mapie';
        if (!region) return;
        if(config.mode!=='defense'&&['base','mine','factory','power'].includes(selectedTarget?.kind)&&selectedTarget.countryId===config.countryId&&(selectedTarget.kind!=='factory'||selectedTarget.health>0))defenseActions(selectedTarget.kind,selectedTarget.id,actions);
        if(own(id)&&!selectedTarget)defenseActions(selectedCity?'city':'region',selectedCity?Number(selectedCity):Number(id),actions);
        if (config.mode === 'defense' && manageable(id)) {
            if(own(id)||permitRegion(id)){button('Rozmieść bazę', () => deployDialog(id),actions,config.baseIcon);lockButton(actions.lastElementChild);}
            if(!own(id)){const host=config.countries?.[String(config.allyRegions?.[String(id)]?.countryId??region.countryId)]||'państwo gospodarza';
                actions.append(make('p',`Region za granicą (${host}). `+(permitRegion(id)?'Pozwolenie na budowę baz jest aktywne. ':'Nowych baz nie można tu budować — pozwolenie wygasło lub zostało zawieszone. ')+'Utrzymanie baz za granicą jest 2× droższe.','military-region-note'));}
            if(regionLocked)actions.append(make('p',LOCKED_TEXT,'military-range-error'));
            for (const base of config.bases.filter(base => base.regionId === id)) {
                const card = make('section', null, 'military-base');card.id=`military-base-${base.id}`;
                const title = make('h3', `${baseName(base)} · poziom ${base.level} / 7`); title.prepend(image(baseIcon(base))); card.append(title);
                for (const [resource, capacity] of Object.entries(base.capacity)) {
                    const info = config.resources[resource], row = make('p', `${info.label}: ${number(base.garrison[resource] || 0)} / ${number(capacity)}`, 'military-resource-label');
                    row.prepend(image(info.icon)); card.append(row);
                }
                card.append(healthBar(base.health));
                const menu=make('details',null,'military-base-menu');const toggle=make('summary','⋮');toggle.setAttribute('aria-label','Opcje bazy');menu.append(toggle);
                const controls = make('div',null,'military-base-actions');menu.append(controls);
                defenseActions('base',base.id,controls);
                button('Zmień nazwę',()=>modal('Nazwa bazy',()=>{const label=make('label','Nazwa'),field=make('input');field.name='name';field.value=baseName(base);field.maxLength=120;field.required=true;label.append(field);fields.append(label);},data=>post({action:'rename',base_id:base.id,name:data.get('name')})),controls);
                button(base.position ? 'Zmień lokalizację' : 'Wskaż miejsce na mapie',()=>startLocation(base),controls,config.baseIcon);
                if(base.position)button('Pokaż bazę',()=>map.setView([base.position[1],base.position[0]],Math.max(map.getZoom(),2)),controls);
                button('Reorganizuj', () => modal(`${base.label} #${base.id} — garnizon`, () => {
                    for (const [resource,capacity] of Object.entries(base.capacity)) input(config.resources[resource].label + ` (pojemność: ${number(capacity)})`,resource,base.garrison[resource] || 0,capacity);
                    fields.append(make('p','Ustaw 0, aby wycofać wybrany rodzaj żołnierzy lub sprzętu.'));
                }, data => post({action:'garrison',base_id:base.id,garrison:Object.fromEntries(Object.keys(base.capacity).map(key => [key,Number(data.get(key))]))})),controls);
                button('Wycofaj garnizon', () => modal('Wycofać garnizon?', () => fields.append(make('p','Żołnierze i sprzęt wrócą do dostępnych zasobów państwa.')), () => post({action:'withdraw',base_id:base.id})),controls);
                button('Zlikwiduj bazę', () => modal('Zlikwidować bazę?', () => {
                    fields.append(make('p',`${baseName(base)} zniknie z mapy, a liczba baz tego rodzaju zmniejszy się o 1.`),
                        make('p','Żołnierze i sprzęt z garnizonu wrócą do dostępnych zasobów państwa. Koszty budowy i rozbudowy nie są zwracane; obrona przeciwrakietowa bazy zostanie usunięta.'));
                }, () => post({action:'liquidate',base_id:base.id})),controls);
                if (base.level < 7) button('Rozbuduj', () => modal('Rozbudowa bazy', () => fields.append(make('p',`Poziom ${base.level + 1}. Koszt: ${number(base.upgradeCost)} ROI z budżetu sił zbrojnych.`)), () => post({action:'upgrade',base_id:base.id})),controls);
                if(base.kind==='naval')for(const kind of ['warships','submarines']){
                    const control=button(`Wyślij: ${config.resources[kind].label}`,()=>startSailing(base,kind),controls,config.resources[kind].icon);
                    control.disabled=!base.position||(base.garrison[kind]||0)<=(base.busyVessels[kind]||0);
                }
                if(base.kind==='naval')carrierButton(base,controls);
                if(!base.operational)card.append(make('p','Silos wyłączony — brak środków na utrzymanie.','military-range-error'));
                if(base.kind==='nuclear'){const months=Number(document.body.dataset.periodMonths)||6,period=document.body.dataset.periodNom||'okres';   // 16 Nov 2026: stawki za bieżący okres (kwartał — połowa półrocza)
                    card.append(make('p',`Utrzymanie: ${500*months/6} mln ROI / ${period}. Rakieta z głowicą nuklearną w silosie: ${650*months/6} mln ROI / ${period}.`));}
                card.append(menu); bases.append(card);
            }
            for(const plant of (config.visiblePower||[]).filter(p=>p.countryId===config.countryId&&p.regionId===String(id))){const card=make('section',null,'military-base military-power-card'),title=make('h3',plant.name);card.id=`military-power-${plant.id}`;title.prepend(image('/static/icons/'+plant.icon));card.append(title,healthBar(plant.health,false),make('p',plant.status+` · ${plant.dailyProduction} e/dzień przy sprawnej elektrowni i dostępnym paliwie`));if(plant.health>0)defenseActions('power',plant.id,card);button('Pokaż elektrownię',()=>map.setView([plant.position[1],plant.position[0]],Math.max(map.getZoom(),3)),card);bases.append(card);}
            for(const factory of (config.visibleFactories||[]).filter(f=>f.countryId===config.countryId&&f.regionId===String(id))){
                const card=make('section',null,'military-base military-factory-card'),title=make('h3',factory.name);card.id=`military-factory-${factory.id}`;title.prepend(image(config.factoryIcon));card.append(title,healthBar(factory.health),make('p',factory.health?`Produkcja: ${factory.dailyProduction} szt. / cykl produkcji Entendy`:'Fabryka zniszczona — produkcja zatrzymana.'));
                if(factory.health>0)defenseActions('factory',factory.id,card);
                button('Pokaż fabrykę',()=>map.setView([factory.position[1],factory.position[0]],Math.max(map.getZoom(),3)),card,config.factoryIcon);bases.append(card);
            }
            for(const mine of (config.visibleMines||[]).filter(item=>item.countryId===config.countryId&&String(item.regionId)===String(id))){
                const card=make('section',null,'military-base military-mine-card');card.id=`military-mine-${mine.id}`;
                const title=make('h3',mine.name);title.prepend(image(config.mineIcon));card.append(title,healthBar(mine.health));
                if(!mine.ready)card.append(make('p',`Budowa kopalni: ${mine.progress}%`));
                defenseActions('mine',mine.id,card);bases.append(card);
            }
            window.GameRadar?.regionPanel(id,actions,bases);
            if(focusedObject?.kind==='power'){const chosen=document.getElementById(`military-power-${focusedObject.id}`);if(chosen)bases.prepend(chosen);}
            highlightSelection();
        } else if (config.mode === 'war') {
            const ownBase=selectedTarget?.kind==='base'&&config.bases.find(base=>base.id===selectedTarget.id);
            if(ownBase){const link=make('a',`Zarządzaj: ${baseName(ownBase)}`);link.href=config.defenseUrl+'?base='+ownBase.id;actions.append(link);if(ownBase.kind==='naval')for(const kind of ['warships','submarines']){const control=button(`Wyślij: ${config.resources[kind].label}`,()=>startSailing(ownBase,kind),actions,config.resources[kind].icon);control.disabled=!ownBase.position||(ownBase.garrison[kind]||0)<=(ownBase.busyVessels[kind]||0);}if(ownBase.kind==='naval')carrierButton(ownBase,actions);return;}
            if (!config.enemyIds.includes(selectedTarget?.countryId ?? region.countryId)) { actions.append(make('p','Działania wojenne są dostępne tylko przeciwko państwom, z którymi trwa wojna.')); return; }
            if(selectedVessel)actions.append(make('p',`Wybrany okręt #${selectedVessel.id}. Kliknij go ponownie, aby zmienić rozkaz.`));
            const methods=[['air','Bombarduj z powietrza'],['missile','Wystrzel rakiety z własnego terytorium'],['naval','Zaatakuj z okrętu'],['land','Wprowadź armię lądową']];
            // 13 Nov 2026: uderzenie atomowe wyłącznie rakietą z głowicą nuklearną z silosu na terytorium kraju (zasięg 3000 km)
            for (const [kind,methodLabel] of methods) for(const nuclear of (kind==='missile'?[false,true]:[false])) {
                if(kind==='land')continue; // replaced by the land invasion (game_land_war.js)
                const label=nuclear?'Wystrzel rakiety z głowicą nuklearną z silosu':methodLabel;
                const sources=sourceBases(kind,nuclear),silos=config.bases.filter(base=>base.kind==='nuclear'&&base.position&&base.operational&&base.health>0&&base.operational&&(base.garrison.warheads||0)>0);
                const ships=(config.vessels||[]).filter(v=>v.countryId===config.countryId&&v.status!=='returning'&&v.health>0&&v.kind!=='carriers');
                const carriers=kind==='air'?(config.vessels||[]).filter(v=>v.countryId===config.countryId&&v.kind==='carriers'&&v.status!=='returning'&&v.health>0&&(v.fighters||0)-(v.busyFighters||0)>0):[];
                const control = button(label, () => modal(label + ' — ' + (selectedTarget?.name || (selectedCity ? config.cities[selectedCity].name : region.name)), () => {
                    if (kind === 'land') {
                        fields.append(make('p','Rozkaz przemarszu nie zmienia jeszcze kontroli regionu.'));
                        for (const resource of ['soldiers','tanks','armored']) input(config.resources[resource].label,resource,0,config.groundInventory[resource]);
                    } else {
                        const options=kind==='naval'?ships.map(v=>[v.id,vesselName(v)]):sources.map(base=>[base.id,`${baseName(base)} — ${config.regions[base.regionId]?.name || ''}`]).concat(carriers.map(v=>['c'+v.id,`${vesselName(v)} — myśliwce: ${(v.fighters||0)-(v.busyFighters||0)}/${v.fighters}`]));
                        const source=choose(kind==='naval'?'Okręt':kind==='air'?'Baza powietrzna lub lotniskowiec':nuclear?'Silos atomowy (rakiety z głowicą nuklearną)':'Baza startowa',kind==='naval'?'vessel_id':'source_base_id',nuclear?sources.map(base=>[base.id,`${baseName(base)} — rakiety: ${number(base.garrison.warheads||0)}`]):options);source.required=true;
                        if(kind==='naval'&&selectedVessel&&ships.some(v=>v.id===selectedVessel.id))source.value=selectedVessel.id;
                        // 17 Nov 2026: wyjaśnienie, gdy żadna baza na terytorium kraju nie ma wyrzutni (np. sprzęt wycofany przy braku środków na utrzymanie).
                        if(kind==='missile'&&!nuclear&&!sources.some(base=>own(base.regionId))){
                            const home=config.bases.filter(base=>base.kind==='land'&&own(base.regionId)).length;
                            if(home)fields.append(make('p',`Żadna z ${home} baz lądowych na terytorium kraju nie ma w garnizonie wyrzutni rakiet. Sprzęt mógł zostać wycofany z garnizonów przy braku środków na utrzymanie wojska. Przydziel wyrzutnie w panelu obrony: baza → „Reorganizuj”.`));
                        }
                        if(nuclear&&kind!=='missile')choose('Silos z głowicami','silo_id',silos.map(base=>[base.id,`${baseName(base)} — głowice: ${number(base.garrison.warheads)}`]));
                        let missile;
                        if(nuclear){missile=make('input');missile.type='hidden';missile.name='missile_type';missile.value='long';fields.append(missile);}
                        else missile=choose('Rodzaj rakiet','missile_type',Object.entries(config.missiles).map(([code,item])=>[code,`${item.label} — zapas: ${number(item.count)}`]));
                        const quantity=input('Liczba rakiet','missiles',1,config.maxSalvo);quantity.min='1';
                        if(!selectedCity&&!selectedTarget)choose('Cel infrastrukturalny','infrastructure',[['road','Drogowa'],['rail','Kolejowa'],['energy','Energetyczna'],['housing','Mieszkaniowa'],['port','Portowa'],['connection','Skomunikowanie']]);
                        fields.append(make('p',selectedTarget?.kind==='factory'?'Jedna trafiona rakieta odbiera 11% życia fabryki.':nuclear?`Rakieta z głowicą nuklearną (zasięg ${number(config.nuclear?.range||3000)} km od silosu). Po trafieniu: skażenie w promieniu ${config.nuclear?.radius||100} km na 3 lata Entendy — giną mieszkańcy miast, zniszczone zostają wszystkie obiekty, obowiązuje zakaz budowy; w regionie degradacja środowiska i zanieczyszczenie powietrza +50, infrastruktura −40…−70. Rakietę może przechwycić obrona przeciwrakietowa. Wszystkie państwa otrzymają powiadomienie.`:selectedTarget?'Każda nieprzechwycona rakieta odbiera od 4 do 15 punktów życia celu.':selectedCity?'Ofiary po trafieniu: od 0 do 100 na nieprzechwyconą rakietę.':'Każda nieprzechwycona rakieta obniża wybraną infrastrukturę o 1 punkt.'));
                        const quote=make('p');fields.append(quote);
                        function update() {
                            const fromCarrier=String(source.value).startsWith('c');
                            const origin=fromCarrier?carriers.find(v=>'c'+v.id===source.value):kind==='naval'?ships.find(v=>v.id===Number(source.value)):sources.find(base=>base.id===Number(source.value));
                            const point=selectedTarget?.point || (selectedCity ? config.cities[selectedCity].point : region.point);
                            if(!origin || !point){quote.textContent='Brak lokalizacji źródła lub celu.';return;}
                            const position=kind==='naval'||fromCarrier?shipPosition(origin,currentGameTime()):origin.position;
                            const distance=Math.hypot(point[0]-position[0],point[1]-position[1])*config.kmPerUnit;
                            const rule=nuclear?{min:0,max:config.nuclear?.range||3000,speed:config.nuclear?.speed||5200}:config.missileRules[missile.value],speed=kind==='air'?config.fighterSpeed:rule.speed;
                            quantity.max=nuclear?Math.min(config.maxSalvo,origin.garrison?.warheads||0):Math.min(config.maxSalvo,config.missiles[missile.value].count);
                            quote.textContent=`Odległość: ${distance.toLocaleString('pl-PL',{maximumFractionDigits:1})} km. Prędkość: ${speed} km/h. Czas do celu: ${(distance/speed).toLocaleString('pl-PL',{maximumFractionDigits:2})} godz. Entendy. `+(kind==='air'?`Zasięg myśliwca: ${config.fighterRange} km (dowolny rodzaj rakiet).`:`Zasięg rakiety: ${rule.min}–${rule.max} km.`);
                            const invalid=kind==='air'?distance>config.fighterRange+0.000001:(distance<rule.min-0.000001||distance>rule.max+0.000001);
                            quote.classList.toggle('military-range-error',invalid);document.getElementById('military-dialog-confirm').disabled=invalid;
                        }
                        source.onchange=update;if(!nuclear)missile.onchange=update;update();
                    }
                }, async data => {
                    const payload = {kind,region_id:Number(id),is_nuclear:nuclear};
                    if(selectedTarget)payload[selectedTarget.kind==='base'?'target_base_id':selectedTarget.kind==='mine'?'target_mine_id':selectedTarget.kind==='defense'?'target_defense_id':selectedTarget.kind==='shipment'?'target_shipment_id':selectedTarget.kind==='power'?'target_power_id':selectedTarget.kind==='factory'?'target_factory_id':selectedTarget.kind==='radar'?'target_radar_id':'target_vessel_id']=selectedTarget.id;
                    if (kind === 'land') for (const resource of ['soldiers','tanks','armored']) payload[resource]=Number(data.get(resource));
                    else {
                        const carrierChoice=kind==='air'&&String(data.get('source_base_id')).startsWith('c');
                        Object.assign(payload,{source_base_id:carrierChoice?null:Number(data.get('source_base_id')),...(carrierChoice?{carrier_id:Number(String(data.get('source_base_id')).slice(1))}:{}),city_id:selectedCity?Number(selectedCity):null,missile_type:data.get('missile_type'),missiles:Number(data.get('missiles')),infrastructure:data.get('infrastructure'),silo_id:Number(data.get('silo_id'))});
                        if(kind==='naval'){const vessel=ships.find(v=>v.id===Number(data.get('vessel_id')));payload.vessel_id=vessel.id;payload.source_base_id=vessel.baseId;}
                    }
                    const response=await fetch(config.orderUrl,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':config.csrf},body:JSON.stringify(payload)});
                    const result=await response.json();if(!response.ok)throw new Error(result.error||'Nie udało się zapisać rozkazu.');
                    dialog.close();document.getElementById('military-feedback').textContent=result.message;
                    if(window.L)await refreshState();
                }),actions,config.attackIcons[kind],true);
                if(kind!=='land' && !(kind==='naval'?ships.length:sources.length+carriers.length)){control.disabled=true;control.title=kind==='naval'?'Wyślij okręt z bazy na mapę.':'Umieść na mapie własną bazę z wymaganym sprzętem.';}
                if(nuclear&&!silos.length)control.disabled=true;
                if(kind==='land')control.disabled=!config.landTargets.includes(Number(id));
            }
            window.GameLandWar?.warActions(actions,{regionId:id,cityId:selectedCity,target:selectedTarget});
        }
    }
    function defenseActions(kind,targetId,parent){
        const defense=(config.defenses||[]).find(item=>item.countryId===config.countryId&&item.targetKind===kind&&item.targetId===targetId);
        if(!defense){
            lockButton(button('Dodaj obronę przeciwrakietową',()=>modal('Obrona przeciwrakietowa — poziom 1',()=>fields.append(make('p','Koszt: 100 000 000 ROI z budżetu wojskowego. 100 pocisków. Skuteczność: 30% na nadlatującą rakietę. Najpierw działa obrona regionu, następnie obrona celu.')),()=>post({action:'defense_place',target_kind:kind,target_id:targetId})),parent,config.defenseIcon));
            return;
        }
        button(`Obrona: poziom ${defense.level} · pociski ${number(defense.ammunition)} / ${number(defense.capacity)}`,()=>showDefense(defense),parent,config.defenseIcon);
    }
    async function showDefense(defense){
        if(config.mode==='defense'){focusedObject=null;highlightSelection();}
        let ammunition=0;if(defense.countryId===config.countryId){try{ammunition=(await load(config.ammunitionStockUrl)).ammunition;}catch{}}
        modal('Obrona przeciwrakietowa',()=>{
            fields.append(make('p',`Poziom ${defense.level}/7. Życie: ${defense.health}%. Skuteczność: ${defense.efficiency}%. Pociski: ${number(defense.ammunition)} / ${number(defense.capacity)}. Obrona działa kolejno: region, a następnie miasto, baza lub kopalnia. Jedno przechwycenie zużywa jeden pocisk.`));
            if(defense.health===0)fields.append(make('p','Obrona niesprawna — wymaga naprawy.'));
            if(defense.countryId!==config.countryId){document.getElementById('military-dialog-confirm').disabled=true;return;}
            const options=[];
            if(defense.health<100)options.push(['repair','Napraw — 10 000 ROI za 1% życia']);
            if(defense.health>0&&defense.level<7)options.push(['upgrade',`Rozbuduj — ${number(defense.upgradeCost)} ROI`]);
            if(defense.health>0&&defense.ammunition<defense.capacity)options.push(['refill','Uzupełnij pociski — 15 000 ROI za sztukę']);
            if(!options.length){fields.append(make('p','Pełne życie, maksymalny poziom i pełny zapas pocisków.'));document.getElementById('military-dialog-confirm').disabled=true;return;}
            const action=choose('Operacja','operation',options),count=input('Liczba procentów życia / pocisków','count',1,10000);count.min='1';
            const source=choose('Źródło amunicji','source',[['purchase','Kup amunicję — 15 000 ROI/szt.'],['stock',`Własna produkcja — magazyn: ${number(ammunition)} szt.`]]);
            source.querySelector('option[value=stock]').disabled=ammunition<1;
            const quote=make('p');fields.append(quote);
            function update(reset=false){const repair=action.value==='repair',quantity=repair||action.value==='refill';count.closest('label').hidden=!quantity;count.disabled=!quantity;source.closest('label').hidden=action.value!=='refill';source.disabled=action.value!=='refill';count.max=repair?100-defense.health:Math.min(defense.capacity-defense.ammunition,source.value==='stock'?ammunition:Infinity);if(reset)count.value=count.max;quote.textContent=quantity?`Koszt: ${number(Number(count.value)*(repair?10000:source.value==='stock'?0:15000))} ROI z budżetu wojskowego.`:'Rozbudowa zwiększa pojemność i dodaje pociski wynikające z różnicy pojemności poziomów.';}
            action.onchange=()=>update(true);source.onchange=()=>update(true);count.oninput=()=>update();update(true);
        },data=>post({action:{repair:'defense_repair',refill:'defense_refill',upgrade:'defense_upgrade'}[data.get('operation')],defense_id:defense.id,count:Number(data.get('count')),source:data.get('source')||'purchase'}));
        if(config.mode==='defense')dialog.classList.add('military-object-selected');
    }
    function drawDefenses(){
        defenseLayer.clearLayers();
        if(!mapFilters.has('defenses'))return;
        for(const defense of config.defenses||[]){
            const base=defense.targetKind==='base'?config.visibleBases.find(base=>base.id===defense.targetId):null;
            const position=base?.position || defense.position;if(!position)continue;
            const compact=defense.targetKind!=='region',size=compact?18:26;
            const badge=make('div',null,'military-defense-symbol military-map-badge'+(compact?' military-defense-symbol-compact':''));badge.append(image(config.defenseIcon),make('span',defense.level));const life=make('progress');life.className='map-health-bar';life.max=100;life.value=defense.health;window.GameHealth?.paint(life,defense.health);badge.append(life);
            const tooltip=make('div',null,'military-defense-tooltip');
            tooltip.append(make('strong','Obrona przeciwrakietowa'));
            for(const [label,value] of [['Życie',`${defense.health}%`],['Poziom',`${defense.level} / 7`],['Skuteczność',`${defense.efficiency}%`],['Pozostałe pociski',`${number(defense.ammunition)} / ${number(defense.capacity)}`]]){
                const row=make('div',null,'military-defense-tooltip-row');row.append(make('span',label),make('strong',value));tooltip.append(row);
            }
            const offset=defense.targetKind==='region'?[13,13]:defense.targetKind==='city'?[9,22]:[23,18];   // 15 Nov 2026: przy obiekcie — lewy górny róg plakietki 26 px
            bindObjectTooltip(L.marker([position[1],position[0]],{icon:L.divIcon({html:badge,className:'military-defense-marker military-map-marker',iconSize:[size,size],iconAnchor:offset}),zIndexOffset:1800}),tooltip,{className:'military-wrapping-tooltip',direction:'auto'})
                .on('click',()=>{if(locating||sailing)return;if(config.mode==='war'&&defense.countryId!==config.countryId&&defense.health>0)showRegion(defense.regionId,null,{kind:'defense',id:defense.id,countryId:defense.countryId,name:'Obrona przeciwrakietowa #'+defense.id,point:position});else showDefense(defense);}).addTo(defenseLayer);
        }
    }
    function sourceBases(kind,nuclear=false) {
        const expected={air:['air','fighters'],missile:nuclear?['nuclear','warheads']:['land','launchers'],naval:['naval','warships']}[kind];
        if(!expected)return [];
        return config.bases.filter(base=>base.kind===expected[0]&&base.position&&base.health>0&&base.operational&&(base.garrison[expected[1]]||0)-(kind==='air'?(base.busyFighters||0):0)>0);
    }
    function healthBar(health,showLabel=true) {
        const box=make('div',null,'military-health');if(showLabel)box.append(make('span',`Życie: ${health} / 100`));
        const bar=make('progress');bar.max=100;bar.value=health;window.GameHealth?.paint(bar,health);bar.setAttribute('aria-label','Życie bazy');box.append(bar);return box;
    }
    async function startLocation(base) {
        if(!regionGeometry){document.getElementById('military-error').textContent='Zaczekaj na wczytanie mapy.';return;}
        cancelLocation();locating=base;locatingLayer=L.layerGroup().addTo(map);
        const outline=L.geoJSON(regionGeometry,{coordsToLatLng:coordinates,filter:feature=>String(feature.properties?.region_id)===base.regionId,
            style:{color:'#218838',weight:2,fillOpacity:base.kind==='naval'?0:.15},interactive:false});
        if(base.kind==='naval')L.geoJSON(regionGeometry,{coordsToLatLng:coordinates,filter:feature=>own(String(feature.properties?.region_id)),style:{color:'#c53434',weight:1,fillColor:'#dc3434',fillOpacity:.35},interactive:false}).addTo(locatingLayer);
        outline.addTo(locatingLayer);
        if(outline.getBounds().isValid())map.fitBounds(outline.getBounds(),{padding:[30,30],maxZoom:7});
        map.getContainer().classList.add('military-locating');
        document.getElementById('military-location-status').textContent=base.kind==='radar'?`Kliknij wewnątrz regionu ${config.regions[base.regionId]?.name}, aby wskazać lokalizację radaru. Lokalizacji nie będzie można zmienić.`:base.kind==='naval'?'Bazę morską postaw na zielonym pasie do 3 km od wybrzeża wybranego regionu. Czerwony obszar jest niedostępny. Przybliż mapę, aby dokładnie wskazać miejsce.':`Kliknij wewnątrz regionu ${config.regions[base.regionId]?.name}, aby wskazać lokalizację bazy.`;
        document.getElementById('military-location-cancel').hidden=false;  // 12 Nov 2026: rezygnacja możliwa także dla nowej bazy
        if(sessionStorage.getItem('military-pending-location-'+config.countryId)===String(base.id)){actions.inert=true;bases.inert=true;selector.disabled=true;}
        map.getContainer().scrollIntoView({block:'center'});
        if(base.kind!=='naval')return;
        try{
            const result=await load(config.coastUrl.replace(/0$/,base.regionId));
            if(locating?.id!==base.id)return;
            if(!result.segments.length){document.getElementById('military-location-status').textContent='Brak wybrzeża na geometrii wybranego regionu. Bazy nie można tu umieścić.';return;}
            coastCleanup=window.GameCoastBand.draw({map,layer:locatingLayer,segments:result.segments,widthKm:result.widthKm,kmPerUnit:config.kmPerUnit,features:regionGeometry.features,regionId:base.regionId});
        }catch(error){if(locating?.id===base.id)document.getElementById('military-location-status').textContent='Nie udało się wczytać pasa wybrzeża. Spróbuj ponownie.';}
    }
    function cancelLocation() {
        actions.inert=false;bases.inert=false;selector.disabled=false;
        if(coastCleanup){coastCleanup();coastCleanup=null;}
        locating=null;sailing=null;redirecting=null;if(locatingLayer){locatingLayer.remove();locatingLayer=null;}
        if(window.L)map.getContainer().classList.remove('military-locating');
        document.getElementById('military-location-status').textContent='';document.getElementById('military-location-cancel').hidden=true;
    }
    async function saveLocation(point) {
        if(savingLocation)return;savingLocation=true;
        try{if(locating.kind==='radar')await window.GameRadar.place(locating,point);else await post({action:'location',base_id:locating.id,x:point.lng,y:point.lat});}
        catch(error){document.getElementById('military-location-status').textContent=error.message;}
        finally{savingLocation=false;}
    }
    document.getElementById('military-location-cancel').onclick=async()=>{
        // Nowo rozmieszczona baza bez lokalizacji: rezygnacja usuwa ją (garnizon i miejsce na bazę wracają).
        const pendingKey='military-pending-location-'+config.countryId;
        if(locating&&locating.kind!=='radar'&&!locating.position&&sessionStorage.getItem(pendingKey)===String(locating.id)){
            if(!window.confirm('Zrezygnować z budowy tej bazy? Garnizon wróci do zasobów państwa.'))return;
            try{await post({action:'cancel_deploy',base_id:locating.id});try{sessionStorage.removeItem(pendingKey);}catch{}location.reload();}
            catch(error){document.getElementById('military-error').textContent=error.message||'Nie udało się zrezygnować z budowy bazy.';}
            return;
        }
        cancelLocation();
    };
    selector.addEventListener('change', () => {if(config.mode==='defense')selectRegion(selector.value);else{showRegion(selector.value);markRegion(selector.value);}});
    document.getElementById('military-dialog-cancel').onclick = () => dialog.close();
    form.onsubmit = async event => {
        event.preventDefault(); const confirm = document.getElementById('military-dialog-confirm'); confirm.disabled = true;
        try { await submit(new FormData(form)); } catch (error) { document.getElementById('military-dialog-error').textContent = error.message; }
        finally { confirm.disabled = false; }
    };
    // The radar module must be ready before the first region panel is drawn (that can happen before the map exists).
    window.GameRadar?.init({config,make,image,number,modal,fields,dialog,input,choose,button,lockButton,defenseActions,healthBar,bindObjectTooltip,mapFilters,startLocation,
        selectObject,showRegion:(...args)=>showRegion(...args),busy:()=>!!(locating||sailing),feedback:text=>{document.getElementById('military-feedback').textContent=text;}});
    const saved = sessionStorage.getItem('military-selected'); if (saved && config.regions[saved] && (config.mode === 'war' || manageable(saved))) setTimeout(()=>showRegion(saved),0);   // 16 Nov 2026: po pełnej inicjalizacji skryptu (mapa, stałe pomocnicze)
    const status = document.getElementById('military-map-status');
    if (!window.L) { status.hidden = false; status.textContent = 'Mapa jest niedostępna. Wybierz region z listy.'; return; }
    const map = L.map('military-map',{crs:L.CRS.Simple,minZoom:-10,maxZoom:8,zoomSnap:.25,attributionControl:false});
    const coordinates = point => L.latLng(point[1],point[0]); map.setView([0,0],0);
    async function load(url) { const response = await fetch(url); if (!response.ok) throw new Error('map'); return response.json(); }
    const baseLayer=L.layerGroup().addTo(map),missionLayers=new Map(),explosionLayer=L.layerGroup().addTo(map);
    let flights=[],gameAnchor=Date.parse(config.gameNow),realAnchor=performance.now(),refreshing=false;
    const mineLayer=L.layerGroup().addTo(map),factoryLayer=L.layerGroup().addTo(map),powerLayer=L.layerGroup().addTo(map);
    function drawMines(){mineLayer.clearLayers();if(!mapFilters.has('mines'))return;for(const mine of config.visibleMines||[]){const symbol=make('div',null,'military-mine-symbol military-map-badge');symbol.style.position='relative';if(config.mode==='defense'&&mapFilters.has('defenses')&&config.defenses.some(item=>item.targetKind==='mine'&&item.targetId===mine.id))symbol.classList.add('military-object-protected');const main=image(config.mineIcon);const badge=image(config.mineralIcons[mine.resource].icon);badge.className='military-map-subbadge';symbol.append(main,badge);const life=make('progress');life.className='map-health-bar';life.max=100;life.value=mine.health;window.GameHealth?.paint(life,mine.health);symbol.append(life);if(!mine.ready){const bar=make('progress');bar.className='mining-build-progress military-mine-progress';bar.max=100;bar.value=mine.progress;bar.setAttribute('aria-label',`Budowa kopalni: ${mine.progress}%`);symbol.append(bar);}const tip=make('div');tip.append(make('strong',mine.name),healthBar(mine.health));bindObjectTooltip(L.marker([mine.position[1],mine.position[0]],{icon:L.divIcon({html:symbol,iconSize:[26,26],iconAnchor:[13,13],className:'military-map-marker'})}),tip).on('click',()=>{if(!locating&&!sailing&&config.mode==='defense'){selectObject('mine',mine);return;}if(!locating&&!sailing)showRegion(mine.regionId,null,{kind:'mine',id:mine.id,countryId:mine.countryId,name:mine.name,point:mine.position});}).addTo(mineLayer);}}
    function drawPower(){powerLayer.clearLayers();if(!mapFilters.has('power'))return;for(const plant of config.visiblePower||[]){const symbol=make('div',null,'military-power-symbol military-map-badge');symbol.append(image('/static/icons/'+plant.icon));const bar=make('progress');bar.className='map-health-bar';bar.max=100;bar.value=plant.health;bar.setAttribute('aria-label','Życie elektrowni');window.GameHealth?.paint(bar,plant.health);symbol.append(bar);const tip=make('div');tip.append(make('strong',plant.name),make('p',plant.status),healthBar(plant.health,false));bindObjectTooltip(L.marker([plant.position[1],plant.position[0]],{icon:L.divIcon({html:symbol,className:'military-map-marker',iconSize:[26,26],iconAnchor:[13,13]})}),tip).on('click',()=>{if(!locating&&!sailing){if(config.mode==='defense')selectObject('power',plant);else if(plant.health>0)showRegion(plant.regionId,null,{kind:'power',id:plant.id,countryId:plant.countryId,name:plant.name,point:plant.position,health:plant.health});}}).addTo(powerLayer);}}
    function drawFactories(){factoryLayer.clearLayers();if(!mapFilters.has('factories'))return;for(const factory of config.visibleFactories||[]){
        if(config.mode==='defense'&&factory.countryId!==config.countryId)continue;
        const symbol=make('div',null,'military-factory-symbol military-map-badge');if(config.mode==='defense'&&mapFilters.has('defenses')&&config.defenses.some(item=>item.targetKind==='factory'&&item.targetId===factory.id))symbol.classList.add('military-object-protected');symbol.append(image(config.factoryIcon));if(factory.productIcon){const product=image(factory.productIcon);product.alt=factory.productName;product.className='military-factory-product military-map-subbadge';symbol.append(product);}
        const life=make('progress');life.className='map-health-bar';life.max=100;life.value=factory.health;window.GameHealth?.paint(life,factory.health);symbol.append(life);
        const tooltip=make('div');tooltip.append(make('strong',factory.name),healthBar(factory.health),make('p',factory.health?`${factory.dailyProduction} szt. / cykl produkcji Entendy`:'Fabryka zniszczona — produkcja zatrzymana.'));
        bindObjectTooltip(L.marker([factory.position[1],factory.position[0]],{icon:L.divIcon({html:symbol,className:'military-map-marker',iconSize:[26,26],iconAnchor:[13,13]})}),tooltip).on('click',()=>{if(config.mode==='war'&&factory.health<=0){document.getElementById('military-feedback').textContent='Fabryka została zniszczona.';return;}if(!locating&&!sailing&&config.mode==='defense'){selectObject('factory',factory);return;}if(!locating&&!sailing)showRegion(factory.regionId,null,{kind:'factory',id:factory.id,countryId:factory.countryId,name:factory.name,point:factory.position,health:factory.health});}).addTo(factoryLayer);
    }}
    function drawBases() {
        baseLayer.clearLayers();
        for(const base of config.visibleBases) {
            if(!base.position||!mapFilters.has(base.kind))continue;
            if(config.mode==='defense'&&base.countryId!==config.countryId)continue;
            const tooltip=make('div',null,'military-base-tooltip');tooltip.append(make('strong',`${baseName(base)} · poziom ${base.level}`));
            for(const [resource,count] of Object.entries(base.garrison)) {
                const info=config.resources[resource];if(!info)continue;
                const row=make('div',`${info.label}: ${number(count)}`,'military-resource-label');row.prepend(image(info.icon));tooltip.append(row);
            }
            if(!Object.keys(base.garrison).length)tooltip.append(make('p',base.intelligenceOnly?'Garnizon — brak danych wywiadowczych.':'Brak garnizonu.'));
            if(base.upkeep!=null&&base.countryId===config.countryId)tooltip.append(make('p',`Utrzymanie: ${number(Number(base.upkeep))} ROI / okres budżetowy${base.abroad?' (baza za granicą — 2×)':''}`));
            tooltip.append(healthBar(base.health));
            window.GameLandWar?.baseTooltip(base,tooltip);
            const symbol=make('div',null,'military-base-symbol military-map-badge');symbol.append(image(baseIcon(base)));window.GameLandWar?.baseSymbol(base,symbol);
            const life=make('progress');life.className='map-health-bar';life.max=100;life.value=base.health;window.GameHealth?.paint(life,base.health);life.setAttribute('aria-label',`Życie bazy: ${base.health} / 100`);symbol.append(life);
            const baseMarker=L.marker([base.position[1],base.position[0]],{icon:L.divIcon({html:symbol,iconSize:[26,26],iconAnchor:[13,13],className:'military-base-map-marker military-map-marker'}),title:baseName(base)});
            (window.GameLandWar?.bindBase(baseMarker,base,tooltip)?baseMarker:bindObjectTooltip(baseMarker,tooltip)).on('click',event=>{if(locating)saveLocation(event.latlng);else if(config.mode==='defense'&&base.countryId===config.countryId){selectObject('base',base);}else if(config.mode==='war'){showRegion(base.regionId,null,{kind:'base',id:base.id,countryId:base.countryId,name:baseName(base),point:base.position});}}).addTo(baseLayer);
        }
    }
    const shipLayer=L.layerGroup().addTo(map),shipMarkers=new Map(),cargoLayer=L.layerGroup().addTo(map),cargoMarkers=new Map(),defenseLayer=L.layerGroup().addTo(map);
    const allFilters=document.getElementById('military-filters-all');
    for(const control of document.querySelectorAll('[data-map-filter]'))control.setAttribute('aria-pressed',String(mapFilters.has(control.dataset.mapFilter)));
    if(allFilters)allFilters.textContent=mapFilters.size===mapFilterKinds.length?'Odznacz wszystkie':'Zaznacz wszystkie';
    if(allFilters)allFilters.onclick=()=>{const select=mapFilters.size!==document.querySelectorAll('[data-map-filter]').length;for(const control of document.querySelectorAll('[data-map-filter]')){if(select)mapFilters.add(control.dataset.mapFilter);else mapFilters.delete(control.dataset.mapFilter);control.setAttribute('aria-pressed',String(select));}allFilters.textContent=select?'Odznacz wszystkie':'Zaznacz wszystkie';saveMapFilters();drawBases();drawDefenses();drawMines();drawFactories();window.GameRadar?.draw();drawPower();if(selectedTarget)showRegion(selected);};
    document.querySelectorAll('[data-map-filter]').forEach(control=>control.addEventListener('click',()=>{const kind=control.dataset.mapFilter;if(mapFilters.has(kind))mapFilters.delete(kind);else mapFilters.add(kind);control.setAttribute('aria-pressed',String(mapFilters.has(kind)));saveMapFilters();if(allFilters)allFilters.textContent=mapFilters.size===document.querySelectorAll('[data-map-filter]').length?'Odznacz wszystkie':'Zaznacz wszystkie';drawBases();drawDefenses();drawMines();drawFactories();window.GameRadar?.draw();drawPower();if(selectedTarget&&['base','mine','defense','factory','power'].includes(selectedTarget.kind)&&!mapFilters.has(selectedTarget.kind==='base'?config.visibleBases.find(base=>base.id===selectedTarget.id)?.kind:selectedTarget.kind==='mine'?'mines':selectedTarget.kind==='defense'?'defenses':selectedTarget.kind==='power'?'power':selectedTarget.kind==='factory'?'factories':null))showRegion(selected);}));
    const vesselName=vessel=>vessel.name||`${vessel.kind==='carriers'?'Lotniskowiec':config.resources[vessel.kind].label} #${vessel.id}`;
    // 12 Nov 2026: lotniskowiec — wybór bazy powietrznej i liczby myśliwców (najwyżej 5), potem punkt na morzu.
    // 16 Nov 2026: deklaracje funkcji (hoisting) — carrierButton bywa wywoływany przy przywracaniu regionu podczas startu skryptu.
    function freeFighters(base){return (base.garrison.fighters||0)-(base.busyFighters||0);}
    function airBasesWithFighters(){return config.bases.filter(b=>b.kind==='air'&&b.health>0&&b.operational&&freeFighters(b)>0);}
    function carrierButton(base,parent){
        const control=button(`Wyślij lotniskowiec (dostępne: ${config.carriersAvailable||0})`,()=>modal('Wysłanie lotniskowca',()=>{
            const air=choose('Baza powietrzna','air_base_id',airBasesWithFighters().map(b=>[b.id,`${baseName(b)} — wolne myśliwce: ${freeFighters(b)}`]));
            const count=input(`Liczba myśliwców (najwyżej ${config.carrierCapacity})`,'fighters',1,config.carrierCapacity);count.min='1';
            const limit=()=>{const chosen=config.bases.find(b=>b.id===Number(air.value));count.max=String(Math.min(config.carrierCapacity,chosen?freeFighters(chosen):0));if(Number(count.value)>Number(count.max))count.value=count.max;};
            air.onchange=limit;limit();fields.append(make('p','Myśliwce pozostają przypisane do bazy powietrznej. Utrata lotniskowca oznacza utratę zaokrętowanych myśliwców. Po zatwierdzeniu wskaż punkt na morzu.'));
        },data=>{dialog.close();startSailing(base,'carriers',{air_base_id:Number(data.get('air_base_id')),fighters:Number(data.get('fighters'))});}),parent,config.vesselIcons.carriers);
        control.disabled=!base.position||!(config.carriersAvailable>0)||!airBasesWithFighters().length;
        return control;
    }
    function currentGameTime(){return MilitaryFlightMath.gameTime(gameAnchor,realAnchor,performance.now(),config.timeMultiplier);}
    function shipPosition(vessel,now){
        return window.GameTradeNavigation.position(vessel,now);
    }
    function startSailing(base,kind,extra=null){
        cancelLocation();sailing={base,kind,extra};map.getContainer().classList.add('military-locating');
        document.getElementById('military-location-status').textContent='Wskaż punkt na wodzie, co najmniej 2 km od wybrzeża. Trasa ominie lądy.';
        document.getElementById('military-location-cancel').hidden=false;
    }
    function renameVessel(vessel){
        modal(vessel.kind==='carriers'?'Nazwa lotniskowca':'Nazwa okrętu',()=>{const label=make('label','Nazwa'),field=make('input');field.name='name';field.value=vesselName(vessel);field.maxLength=120;field.required=true;label.append(field);fields.append(label);},data=>post({action:'rename_vessel',vessel_id:vessel.id,name:data.get('name')}));
    }
    function drawShips(){
        const openVessel=[...shipMarkers].find(([id,marker])=>marker.isPopupOpen())?.[0];
        const hoveredVessel=[...shipMarkers].find(([id,marker])=>marker.isTooltipOpen())?.[0];   // odświeżenie stanu nie zamyka tooltipu
        shipLayer.clearLayers();shipMarkers.clear();
        // 17 Nov 2026: okręty stojące w tym samym punkcie (np. na pozycji w porcie) rozsuwamy wachlarzem,
        // aby każdy był widoczny i klikalny — wcześniej ikony nakładały się i atak trafiał w okręt z wierzchu.
        const stackIndex=new Map(),stackSize=new Map(),stackKey=vessel=>{const p=shipPosition(vessel,currentGameTime());return `${Math.round(p[0]*2)}:${Math.round(p[1]*2)}`;};
        for(const vessel of config.vessels||[]){const k=stackKey(vessel);stackIndex.set(vessel.id,stackSize.get(k)||0);stackSize.set(k,(stackSize.get(k)||0)+1);}
        const stackAnchor=vessel=>{const n=stackSize.get(stackKey(vessel))||1,i=stackIndex.get(vessel.id)||0;if(n<2)return [13,13];const angle=2*Math.PI*i/n-Math.PI/2,r=n<=4?16:20;return [Math.round(13-r*Math.cos(angle)),Math.round(13-r*Math.sin(angle))];};
        for(const vessel of config.vessels||[]){
            const position=shipPosition(vessel,currentGameTime());
            // 14 Nov 2026: trasa okrętu widoczna dopiero po najechaniu na okręt (dymek) albo przy otwartym menu okrętu.
            const route=(vessel.status==='sailing'||vessel.status==='returning')?L.polyline((vessel.route||[vessel.source,vessel.target]).map(p=>[p[1],p[0]]),{color:'#ffffff',dashArray:'5 5',weight:2,opacity:.85,interactive:false}):null;
            const symbol=make('div',null,'military-vessel-symbol military-map-badge military-map-vessel');symbol.append(image(config.vesselIcons[vessel.kind]));const life=make('progress');life.className='map-health-bar';life.max=100;life.value=vessel.health;window.GameHealth?.paint(life,vessel.health);symbol.append(life);
            if(vessel.countryId!==config.countryId){const flag=image(config.flags[String(vessel.countryId)],config.countries[String(vessel.countryId)]);flag.className='military-vessel-flag';symbol.append(flag);}
            const marker=bindObjectTooltip(L.marker([position[1],position[0]],{icon:L.divIcon({html:symbol,className:'military-vessel military-map-marker',iconSize:[26,26],iconAnchor:stackAnchor(vessel)}),zIndexOffset:1700}),make('span',`${vessel.countryId!==config.countryId?(config.countries[String(vessel.countryId)]||'Obce państwo')+' · ':''}${vesselName(vessel)} · życie: ${vessel.health}/100 · ${vessel.status==='returning'?'powrót do bazy':vessel.status==='sailing'?'w rejsie':'na pozycji'} · ${config.vesselSpeed} km/h`)).addTo(shipLayer);
            if(route){const sync=()=>{if(marker.isTooltipOpen()||marker.isPopupOpen())route.addTo(shipLayer);else route.remove();};marker.on('tooltipopen popupopen',()=>route.addTo(shipLayer)).on('tooltipclose popupclose',()=>setTimeout(sync,0));}
            marker.on('click',()=>{
                if(vessel.countryId!==config.countryId){
                    if(config.mode==='war'){const home=config.visibleBases.find(base=>base.id===vessel.baseId),regionId=home?.regionId||vessel.regionId||Object.keys(config.regions).find(id=>config.regions[id].countryId===vessel.countryId);if(regionId)showRegion(regionId,null,{kind:'vessel',id:vessel.id,countryId:vessel.countryId,name:vesselName(vessel),point:shipPosition(vessel,currentGameTime())});}
                    return;
                }
                if(config.mode==='defense'){focusedObject=null;highlightSelection();}
                const content=make('div',null,config.mode==='defense'?'military-object-selected':'');content.append(make('strong',vesselName(vessel)),healthBar(vessel.health));
                if(vessel.kind==='carriers')content.append(make('p',`Myśliwce: ${(vessel.fighters||0)-(vessel.busyFighters||0)} wolne z ${vessel.fighters||0} · zasięg ${config.fighterRange} km`));
                button(vessel.kind==='carriers'?'Zmień nazwę lotniskowca':'Zmień nazwę okrętu',()=>{marker.closePopup();renameVessel(vessel);},content);
                button('Wskaż nowy kierunek',()=>{marker.closePopup();cancelLocation();redirecting=vessel;map.getContainer().classList.add('military-locating');
                    document.getElementById('military-location-status').textContent=`${vesselName(vessel)}: wskaż nowy punkt na wodzie. Trasa ominie lądy.`;document.getElementById('military-location-cancel').hidden=false;},content);
                button('Powrót do bazy',()=>{marker.closePopup();modal('Wybierz bazę morską',()=>choose('Baza docelowa','base_id',config.bases.filter(b=>b.kind==='naval'&&b.position&&b.health>0).map(b=>[b.id,baseName(b)])),data=>post({action:'return_vessel',vessel_id:vessel.id,base_id:Number(data.get('base_id'))}));},content);
                const launch=button('Wystrzel rakiety',()=>{selectedVessel=vessel;marker.closePopup();if(config.mode==='defense'){sessionStorage.setItem('military-vessel',vessel.id);location.href=config.warUrl;}else{document.getElementById('military-feedback').textContent=`Wybrano okręt #${vessel.id}. Kliknij miasto lub region celu, następnie „Zaatakuj z okrętu”.`;if(selected)showRegion(selected,selectedCity,selectedTarget);}},content);
                launch.disabled=vessel.status==='returning'||!config.enemyIds.length;
                if(vessel.kind==='carriers')launch.remove();   // z lotniskowca: „Bombarduj z powietrza” przy celu
                marker.bindPopup(content).openPopup();
            });shipMarkers.set(vessel.id,marker);
        }
        if(openVessel&&!dialog.open)shipMarkers.get(openVessel)?.fire('click');
        else if(hoveredVessel&&!dialog.open)shipMarkers.get(hoveredVessel)?.openTooltip();
        const remembered=Number(sessionStorage.getItem('military-vessel'));if(remembered&&!selectedVessel)selectedVessel=(config.vessels||[]).find(v=>v.id===remembered)||null;
    }
    function drawCargoShips(){
        cargoLayer.clearLayers();cargoMarkers.clear();if(config.mode!=='war')return;
        for(const ship of config.tradeShips||[]){
            const point=window.GameTradeNavigation.position(ship,currentGameTime());if(!point||Date.parse(ship.arrivesAt)<=currentGameTime())continue;
            const symbol=make('div',null,'military-vessel-symbol trade-cargo-symbol military-map-badge');symbol.append(image(config.cargoShipIcon));
            const flag=image(config.flags[String(ship.originCountryId)],'Kraj wypłynięcia');flag.className='military-vessel-flag';symbol.append(flag);
            const life=make('progress');life.className='map-health-bar';life.max=100;life.value=ship.health;window.GameHealth?.paint(life,ship.health);symbol.append(life);
            const route=L.polyline(ship.route.map(p=>[p[1],p[0]]),{color:ship.canAttack?'#c07b6d':'#7e9d75',weight:2,dashArray:'6 7',interactive:false}).addTo(cargoLayer);
            const marker=L.marker([point[1],point[0]],{icon:L.divIcon({html:symbol,className:'military-map-marker',iconSize:[26,26],iconAnchor:[13,13]}),zIndexOffset:1750}).bindTooltip(make('span',`Statek handlowy #${ship.id} · ${ship.seller} → ${ship.buyer} · życie ${ship.health}%`)).addTo(cargoLayer);
            marker.on('click',()=>{if(locating||sailing)return;if(ship.canAttack)showRegion(ship.regionId,null,{kind:'shipment',id:ship.id,countryId:ship.countryId,name:`Statek handlowy #${ship.id}`,point:window.GameTradeNavigation.position(ship,currentGameTime())});else marker.bindPopup(make('span','Statek własny lub neutralny — atak niedostępny.')).openPopup();});
            cargoMarkers.set(ship.id,{marker,route});
        }
    }
    function animateShips(now){for(const ship of config.tradeShips||[]){const entry=cargoMarkers.get(ship.id);if(!entry)continue;if(now>=Date.parse(ship.arrivesAt)){entry.marker.remove();entry.route.remove();cargoMarkers.delete(ship.id);}else{const point=window.GameTradeNavigation.position(ship,now);entry.marker.setLatLng([point[1],point[0]]);}}for(const vessel of config.vessels||[]){const point=shipPosition(vessel,now);shipMarkers.get(vessel.id)?.setLatLng([point[1],point[0]]);}}
    function updateFlights(items,now) {
        flights=items;gameAnchor=Date.parse(now);realAnchor=performance.now();
        const keep=new Set();
        for(const flight of flights) {
            if(flight.radarOnly){
                const end=Math.max(...flight.radarTrack.map(piece=>Date.parse(piece.toAt)));
                if(end<=gameAnchor)continue;
                keep.add(flight.id);missionLayers.get(flight.id)?.group.remove();
                missionLayers.set(flight.id,radarSighting(flight));continue;
            }
            const end=Date.parse(flight.returnsAt||flight.impactAt);
            if(flight.returnedAt||end<=gameAnchor)continue;
            keep.add(flight.id);
            if(missionLayers.has(flight.id))continue;
            const group=L.layerGroup().addTo(map);
            L.polyline([[flight.source[1],flight.source[0]],[flight.target[1],flight.target[0]]],{color:'#c53434',weight:1.5,dashArray:'6 5',opacity:.65,interactive:false}).addTo(group);
            const dot=make('span',null,'military-missile-pulse');
            const rocket=flight.kind==='air'?null:L.marker([flight.source[1],flight.source[0]],{icon:L.divIcon({className:'military-missile',html:dot,iconSize:[14,14],iconAnchor:[7,7]}),zIndexOffset:1500})
                .bindTooltip(make('span',`${flight.targetName} · rakiety: ${flight.missiles} · ${flight.distanceKm.toLocaleString('pl-PL',{maximumFractionDigits:1})} km`)).addTo(group);
            let jet=null,jetImage=null;
            if(flight.kind==='air') {
                jetImage=image(config.fighterIcon,'Myśliwiec');const wrapper=make('div',null,'military-fighter-icon');wrapper.append(jetImage);
                jet=L.marker([flight.source[1],flight.source[0]],{icon:L.divIcon({className:'military-fighter',html:wrapper,iconSize:[36,36],iconAnchor:[18,18]}),zIndexOffset:1600})
                    .bindTooltip(make('span',`Myśliwiec ${flight.sourceBaseId?'z bazy #'+flight.sourceBaseId:'ze zniszczonej bazy'} — ${flight.targetName}, następnie powrót`)).addTo(group);
            }
            missionLayers.set(flight.id,{group,rocket,jet,jetImage});
        }
        for(const [id,entry] of missionLayers)if(!keep.has(id)){entry.group.remove();missionLayers.delete(id);}
        const history=document.getElementById('military-flights');
        if(history) {
            history.replaceChildren();
            if(!items.some(item=>!item.radarOnly)){const empty=make('div',null,'war-log-empty');empty.append(make('strong','Brak meldunków operacyjnych'),make('p','Wybierz cel na mapie, aby zaplanować pierwsze uderzenie. Tutaj zobaczysz przebieg lotów i skutki ataków.'));history.append(empty);}
            for(const flight of [...items].filter(item=>!item.radarOnly).sort((a,b)=>b.id-a.id)) {
                const text=`${flight.targetName} · ${number(flight.missiles)} rakiet · ${flight.distanceKm.toLocaleString('pl-PL',{maximumFractionDigits:1})} km · `;
                const status=flight.impactedAt?`Trafienie. ${flight.isNuclear?(flight.damage?.nuclear?'Wybuch jądrowy — skażenie 100 km, ofiary: '+number(flight.casualties||0):'Rakieta atomowa przechwycona — brak skażenia.'):'Ofiary: '+number(flight.casualties||0)}${flight.kind==='air'&&!flight.returnedAt?' · Myśliwiec wraca do bazy.':''}`:
                    `Planowane trafienie (Entenda): ${new Intl.DateTimeFormat('pl-PL',{timeZone:'UTC',dateStyle:'short',timeStyle:'short'}).format(new Date(flight.impactAt))}`;
                const damage=flight.damage||{};
                const effects=` · Przechwycono: ${number(flight.intercepted||0)}`+(damage.infrastructure?` · Utrata infrastruktury: ${number(damage.infrastructurePoints)} pkt`:damage.factoryHealthLost!=null?` · Uszkodzenie fabryki: ${number(damage.factoryHealthLost)}% życia${damage.factoryDestroyed?' · Zniszczona':''}`:damage.baseHealthLost!=null?` · Uszkodzenie bazy: ${number(damage.baseHealthLost)} pkt życia`:damage.vesselHealthLost!=null?` · Uszkodzenie okrętu: ${number(damage.vesselHealthLost)} pkt życia${damage.sunk?' · Zatopiony':''}`:'');
                if(warTheme){const card=make('article',null,'war-operation');const heading=make('div',null,'war-operation-heading');heading.append(make('strong',flight.targetName),make('span',flight.returnedAt?'Zakończono':flight.impactedAt?'Powrót do bazy':'W drodze','war-operation-status'));card.append(heading,make('p',`${flight.kind==='air'?'Operacja lotnicza':'Uderzenie rakietowe'} · ${number(flight.missiles)} rakiet · ${flight.distanceKm.toLocaleString('pl-PL',{maximumFractionDigits:1})} km`),make('p',status+effects));history.append(card);}else history.append(make('p',text+status+effects));
            }
        }
    }
    function radarSighting(flight){
        // A foreign flight seen by our radar: only the pieces inside the radar range, never the launch site.
        const group=L.layerGroup().addTo(map);
        for(const piece of flight.radarTrack)L.polyline([[piece.from[1],piece.from[0]],[piece.to[1],piece.to[0]]],{color:'#ff9800',weight:2,dashArray:'4 6',opacity:.85,interactive:false}).addTo(group);
        const who=config.countries[String(flight.countryId)]||'Obce państwo';
        const text=`Wykryte przez radar · ${who} · ${flight.kind==='air'?'myśliwiec':number(flight.missiles)+' rakiet'} · cel: ${flight.targetName}`;
        let icon,jetImage=null;if(flight.kind==='air'){const wrapper=make('div',null,'military-fighter-icon military-radar-contact');const jet=image(config.fighterIcon,'Myśliwiec');wrapper.append(jet);jetImage=jet;jet.style.transform=`rotate(${MilitaryFlightMath.heading(flight.radarTrack[0].from,flight.radarTrack[flight.radarTrack.length-1].to)}deg)`;icon=L.divIcon({className:'military-fighter',html:wrapper,iconSize:[36,36],iconAnchor:[18,18]});}
        else icon=L.divIcon({className:'military-missile military-radar-contact',html:make('span',null,'military-missile-pulse'),iconSize:[14,14],iconAnchor:[7,7]});
        const first=flight.radarTrack[0].from;
        const marker=L.marker([first[1],first[0]],{icon,zIndexOffset:1600,opacity:0}).bindTooltip(make('span',text)).addTo(group);
        return {group,radar:marker,jetImage,track:flight.radarTrack.map(piece=>({...piece,start:Date.parse(piece.fromAt),end:Date.parse(piece.toAt)}))};
    }
    // 14 Nov 2026: wybuch w miejscu trafienia — tylko gdy animacja na żywo dociera do celu (nie przy wczytaniu dawnych ataków).
    function explode(flight){
        if(flight.impactedAt&&(flight.intercepted||0)>=flight.missiles)return;   // wszystkie rakiety przechwycone
        const nuclear=!!flight.isNuclear,size=nuclear?120:56;
        const blast=make('div',null,'military-explosion'+(nuclear?' is-nuclear':''));
        blast.append(make('span',null,'military-explosion-flash'),make('span',null,'military-explosion-ring'));
        const marker=L.marker([flight.target[1],flight.target[0]],{icon:L.divIcon({className:'military-explosion-icon',html:blast,iconSize:[size,size],iconAnchor:[size/2,size/2]}),interactive:false,keyboard:false,zIndexOffset:1700}).addTo(explosionLayer);
        setTimeout(()=>marker.remove(),nuclear?2600:1400);
    }
    function animate() {
        const now=MilitaryFlightMath.gameTime(gameAnchor,realAnchor,performance.now(),config.timeMultiplier);
        for(const flight of flights) {
            const entry=missionLayers.get(flight.id);if(!entry)continue;
            if(entry.radar){
                const piece=entry.track.find(item=>now>=item.start&&now<item.end);
                if(now>=Math.max(...entry.track.map(item=>item.end))){entry.group.remove();missionLayers.delete(flight.id);continue;}
                if(piece){const f=(now-piece.start)/Math.max(1,piece.end-piece.start);if(entry.jetImage)entry.jetImage.style.transform=`rotate(${MilitaryFlightMath.heading(piece.from,piece.to)}deg)`;entry.radar.setLatLng([piece.from[1]+(piece.to[1]-piece.from[1])*f,piece.from[0]+(piece.to[0]-piece.from[0])*f]).setOpacity(1);}
                else entry.radar.setOpacity(0);
                continue;
            }
            const point=MilitaryFlightMath.sample(flight,now),impact=Date.parse(flight.impactAt);
            if(entry.lastNow!==undefined&&entry.lastNow<impact&&now>=impact&&now-impact<=2000*config.timeMultiplier){explode(flight);refreshAfterImpact();}
            entry.lastNow=now;
            if(now>=Date.parse(flight.returnsAt||flight.impactAt)){entry.group.remove();missionLayers.delete(flight.id);continue;}
            if(entry.rocket)entry.rocket.setLatLng(point.rocket).setOpacity(point.rocketVisible?1:0);
            if(entry.jet) {
                entry.jet.setLatLng(point.jet).setOpacity(point.jetVisible?1:0);
                entry.jetImage.style.transform=`rotate(${point.bearing}deg)`;
            }
        }
        animateShips(now);
        window.GameLandWar?.tick(now);
        requestAnimationFrame(animate);
    }
    // 15 Nov 2026: telefon — zapytanie o stan może „zawisnąć” (uśpiona karta, zmiana sieci); bez limitu czasu flaga
    // refreshing zostawała ustawiona na zawsze i mapa przestawała pokazywać utratę życia i zniszczenie obiektów.
    let refreshStarted=0,refreshAgain=false,impactRefresh=null;
    async function refreshState() {
        if(!window.L)return;
        if(refreshing&&performance.now()-refreshStarted<20000){refreshAgain=true;return;}
        refreshing=true;refreshStarted=performance.now();refreshAgain=false;
        const abort=window.AbortController?new AbortController():null,timer=abort?setTimeout(()=>abort.abort(),15000):null;
        try {
            const response=await fetch(config.stateUrl,{credentials:'same-origin',cache:'no-store',signal:abort?.signal});
            if(!response.ok)throw new Error('state');const state=await response.json();
            config.visiblePower=state.power||[];config.visibleFactories=state.factories||[];config.tradeShips=state.tradeShips||[];config.visibleMines=state.mines;config.visibleBases=state.bases;config.bases=state.bases.filter(base=>base.countryId===config.countryId);config.missiles=state.missiles;config.vessels=state.vessels;config.defenses=state.defenses;
            config.gameNow=state.gameNow;config.timeMultiplier=state.timeMultiplier;updateReadiness(state.flights);window.GameLandWar?.update(state);if(state.radars)config.radars=state.radars;drawBases();drawMines();drawFactories();window.GameRadar?.draw();drawPower();updateFlights(state.flights,state.gameNow);drawShips();drawCargoShips();drawDefenses();
            if(selectedTarget?.kind==='power'){const plant=(config.visiblePower||[]).find(p=>p.id===selectedTarget.id);if(plant){selectedTarget.health=plant.health;selectedTarget.point=plant.position;}else{selectedTarget=null;focusedObject=null;}}
            if(selectedTarget?.kind==='factory'){const factory=config.visibleFactories.find(f=>f.id===selectedTarget.id);if(factory){selectedTarget.health=factory.health;selectedTarget.point=factory.position;if(config.mode==='war'&&factory.health<=0)selectedTarget=null;}else selectedTarget=null;}
            if(selectedTarget?.kind==='radar'){const radar=(config.radars||[]).find(r=>r.id===selectedTarget.id);if(radar&&radar.health>0)selectedTarget.health=radar.health;else{selectedTarget=null;if(config.mode==='war')actions.replaceChildren();}}
            if(selectedTarget?.kind==='shipment'){const ship=config.tradeShips.find(s=>s.id===selectedTarget.id);if(ship&&ship.canAttack)selectedTarget.point=window.GameTradeNavigation.position(ship,currentGameTime());else{selectedTarget=null;actions.replaceChildren();document.getElementById('military-feedback').textContent='Statek zakończył rejs lub został zatopiony.';}}
            if(selectedTarget?.kind==='vessel'){const vessel=config.vessels.find(v=>v.id===selectedTarget.id);if(vessel)selectedTarget.point=shipPosition(vessel,currentGameTime());}
            if(selected&&!dialog.open&&!locating&&!sailing&&!document.querySelector('.military-base-menu[open]'))showRegion(selected,selectedCity,selectedTarget);
            const status=document.getElementById('military-map-status');if(status&&status.dataset.refreshError){status.hidden=true;status.textContent='';delete status.dataset.refreshError;}
        } catch(error) {const status=document.getElementById('military-map-status');status.hidden=false;status.dataset.refreshError='1';status.textContent='Nie udało się odświeżyć stanu lotów. Ponawiam próbę.';}
        finally {if(timer)clearTimeout(timer);refreshing=false;if(refreshAgain){refreshAgain=false;setTimeout(refreshState,250);}}
    }
    // Po trafieniu (animacja dociera do celu) stan odświeżany od razu, nie dopiero przy kolejnym cyklu 5 s.
    function refreshAfterImpact(){clearTimeout(impactRefresh);impactRefresh=setTimeout(refreshState,1500);}
    window.GameLandWar?.init({map,config,make,image,number,modal,fields,dialog,input,choose,currentGameTime,refresh:()=>refreshState(),own,baseName,
        showRegion:(...args)=>showRegion(...args),feedback:text=>{document.getElementById('military-feedback').textContent=text;}});
    window.GameRadar?.attach(map);
    const rawDistance=map.distance.bind(map);map.distance=(a,b)=>rawDistance(a,b)*config.kmPerUnit*1000;
    L.control.scale({imperial:false,metric:true}).addTo(map);
    requestAnimationFrame(animate);
    document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshState();});
    // Telefon: powrót do karty z pamięci podręcznej przeglądarki, do aplikacji lub do sieci.
    window.addEventListener('pageshow',event=>{if(event.persisted)refreshState();});
    window.addEventListener('focus',()=>refreshState());window.addEventListener('online',()=>refreshState());

    Promise.allSettled([load(config.regionsUrl),load(config.countriesUrl),load(config.citiesUrl)]).then(results => {
        const empty = {type:'FeatureCollection',features:[]};
        const [regions,countries,cities] = results.map(result => result.status === 'fulfilled' ? result.value : empty);
        regionGeometry=regions;window.GameLandWar?.setRegions(regions,coordinates);
        if (config.mode === 'defense') L.geoJSON(countries,{coordsToLatLng:coordinates,filter:feature => !config.controlledCountryIds.includes(Number(feature.properties?.panstwo_id)),
            style:{color:DEF.border,weight:1.2,fillColor:DEF.land,fillOpacity:1},onEachFeature:(feature,layer) => {
                const label = make('span',config.countries[String(feature.properties?.panstwo_id)] || 'Państwo'); layer.bindTooltip(label,{sticky:true,className:'military-world-tooltip'});
            }}).addTo(map);
        if (config.mode === 'defense' && Object.keys(config.allyRegions||{}).length) {
            // 12 Nov 2026: regiony sojuszników (jasnozielone) i regiony z pozwoleniem na bazę (żółtawe).
            const allyFill=r=>r.permit==='ACTIVE'?DEF.permit:r.permit==='FROZEN'?DEF.frozen:DEF.ally;
            const allyLayer=L.geoJSON(regions,{coordsToLatLng:coordinates,filter:feature=>!!config.allyRegions[String(feature.properties?.region_id)],
                style:feature=>({color:DEF.border,weight:1,fillColor:allyFill(config.allyRegions[String(feature.properties.region_id)]),fillOpacity:1}),
                onEachFeature:(feature,layer)=>{
                    const id=String(feature.properties.region_id), r=config.allyRegions[id];
                    layer.bindTooltip(make('span',`${r.name} — ${config.countries[String(r.countryId)]||'sojusznik'}`),{sticky:true});
                    layer.on({mouseover:()=>layer.setStyle({weight:2,fillColor:DEF.hover}),mouseout:()=>allyLayer.resetStyle(layer),click:event=>{
                        if(locating||sailing||redirecting)return;
                        const box=make('div',null,'military-base-tooltip');box.append(make('strong',r.name),make('p',`Terytorium sojusznika: ${config.countries[String(r.countryId)]||''}`));
                        const ownHere=config.bases.filter(base=>String(base.regionId)===id).length;
                        if(ownHere)button(`Zarządzaj bazami (${ownHere})`,()=>{map.closePopup();showRegion(id);},box,config.baseIcon);
                        if(r.permit==='ACTIVE'){box.append(make('p','Masz pozwolenie na budowę bazy. Utrzymanie bazy za granicą jest 2× droższe.'));button('Zbuduj bazę',()=>{map.closePopup();deployDialog(id);},box,config.baseIcon);}
                        else if(r.permit==='FROZEN')box.append(make('p','Pozwolenie zawieszone: relacje spadły poniżej sojuszniczych. Istniejące bazy zostają, nowych nie można budować.'));
                        else if(r.pending)box.append(make('p','Prośba o pozwolenie na budowę bazy oczekuje na decyzję.'));
                        else button('Poproś o możliwość budowy bazy',async()=>{
                            const form=new FormData();form.append('csrf_token',config.csrf);form.append('target_id',String(r.countryId));form.append('kind','BASE_PERMIT');form.append('region_id',id);
                            try{const response=await fetch(config.diplomacyActionUrl,{method:'POST',credentials:'same-origin',body:form,headers:{Accept:'application/json'}});const data=await response.json();
                                if(!response.ok)throw new Error(data.error||'Nie udało się wysłać prośby.');r.pending=true;map.closePopup();document.getElementById('military-feedback').textContent='Wysłano prośbę o pozwolenie na budowę bazy. Otrzymasz powiadomienie o decyzji.';}
                            catch(error){document.getElementById('military-error').textContent=error.message;}
                        },box);
                        L.popup().setLatLng(event.latlng).setContent(box).openOn(map);
                    }});
                }}).addTo(map);
        }
        const regionLayer = regionLayerRef = L.geoJSON(regions,{
            coordsToLatLng:coordinates,filter:feature => config.mode === 'war' ? !!config.regions[String(feature.properties?.region_id)] : metropolitan.has(String(feature.properties?.region_id)),
            // 13 Nov 2026: obie mapy (obrona i panel wojenny) w kolorystyce mapy świata; przeciwnik — stonowana czerwień.
            style:feature => {const id=String(feature.properties.region_id);
                if(highlightedRegion===id)return {color:DEF.selected,weight:2.5,fillColor:DEF.hover,fillOpacity:1};
                const fill=own(id)?DEF.own:warTheme&&config.enemyIds.includes(config.regions[id]?.countryId)?DEF.enemy:warTheme?DEF.land:DEF.own;
                return {color:DEF.regionBorder,weight:warTheme?.6:.8,fillColor:fill,fillOpacity:1};},
            onEachFeature:(feature,layer) => {
                const id = String(feature.properties.region_id), region = config.regions[id];
                if(config.mode==='defense'){const existing=regionBounds.get(id);regionBounds.set(id,existing?existing.extend(layer.getBounds()):L.latLngBounds(layer.getBounds()));}
                layer.bindTooltip(()=>window.GameLandWar?window.GameLandWar.regionTooltip(id,region):make('span',region.name),{sticky:true,className:'military-world-tooltip'});
                layer.on({mouseover:()=>layer.setStyle({fillColor:DEF.hover}),mouseout:()=>regionLayer.resetStyle(layer),click:()=>{if(!locating&&!sailing){if(config.mode==='defense')selectRegion(id);else{showRegion(id);markRegion(id);}revealManagement();}}});
            }
        }).addTo(map);
        {
            // Granice państw grubszą linią (obrona: tylko własne) i siatka południków jak na mapie świata.
            map.createPane('defenseBorders');map.getPane('defenseBorders').style.zIndex='405';map.getPane('defenseBorders').style.pointerEvents='none';
            L.geoJSON(countries,{pane:'defenseBorders',coordsToLatLng:coordinates,interactive:false,filter:feature=>warTheme||config.controlledCountryIds.includes(Number(feature.properties?.panstwo_id)),style:{color:DEF.border,weight:warTheme?1.8:2.2,fill:false}}).addTo(map);
            const area=regionLayer.getBounds();
            if(area.isValid()){
                map.createPane('defenseGrid');map.getPane('defenseGrid').style.zIndex='350';map.getPane('defenseGrid').style.pointerEvents='none';
                const h=area.getNorth()-area.getSouth(),w=area.getEast()-area.getWest(),pad=Math.max(h,w)*1.5,step=Math.max(h,w)/(warTheme?14:8)||1;
                const s0=area.getSouth()-pad,n0=area.getNorth()+pad,w0=area.getWest()-pad,e0=area.getEast()+pad,grid={pane:'defenseGrid',color:'#ffffff',weight:.6,opacity:.16,interactive:false,dashArray:'3 5'};
                for(let y=Math.floor(s0/step)*step;y<=n0;y+=step)L.polyline([[y,w0],[y,e0]],grid).addTo(map);
                for(let x=Math.floor(w0/step)*step;x<=e0;x+=step)L.polyline([[s0,x],[n0,x]],grid).addTo(map);
            }
        }
        map.createPane('militaryCities'); map.getPane('militaryCities').style.zIndex = '450'; applyCityFilter();
        L.geoJSON(cities,{coordsToLatLng:coordinates,filter:feature => !!config.cities[String(feature.properties?.miasto_id)] && (config.mode === 'war' || config.cities[String(feature.properties.miasto_id)].countryId !== config.countryId || metropolitan.has(config.cities[String(feature.properties.miasto_id)].regionId)),
            pointToLayer:(feature,latlng)=>L.circleMarker(latlng,{pane:'militaryCities',radius:warTheme?3.5:4,color:DEF.cityBorder,weight:1.2,fillColor:DEF.city,fillOpacity:1}),
            onEachFeature:(feature,layer)=>{const city=config.cities[String(feature.properties.miasto_id)];if(window.GameLandWar)window.GameLandWar.bindCity(layer,String(feature.properties.miasto_id),city);else bindObjectTooltip(layer,make('span',city.name));layer.on('click',()=>{if(!locating&&!sailing&&config.regions[city.regionId]&&(config.mode==='war'||own(city.regionId))){if(config.mode==='defense'){focusedObject={kind:'city',id:String(feature.properties.miasto_id)};framedRegion=null;}showRegion(city.regionId,String(feature.properties.miasto_id));highlightSelection(config.mode==='defense');}});}
        }).addTo(map);
        const myCountryButton=document.getElementById('war-map-country');
        if(myCountryButton){const home=L.geoJSON(regions,{coordsToLatLng:coordinates,filter:feature=>metropolitan.has(String(feature.properties?.region_id))});const homeBounds=home.getBounds();myCountryButton.disabled=!homeBounds.isValid();myCountryButton.onclick=()=>{if(homeBounds.isValid())map.fitBounds(homeBounds,{padding:[30,30],maxZoom:5});};}
        const bounds = regionLayer.getBounds(); if (bounds.isValid()) {map.fitBounds(bounds,{padding:[30,30],maxZoom:5,animate:false});const reset=document.getElementById('war-map-reset');if(reset)reset.onclick=()=>{framedRegion=null;map.fitBounds(bounds,{padding:[30,30],maxZoom:5});};}
        else { status.hidden=false; status.textContent='Brak geometrii regionów.'; }
        const pendingId=Number(sessionStorage.getItem('military-pending-location-'+config.countryId));const pendingBase=config.bases.find(base=>base.id===pendingId);
        if(config.mode==='defense'&&pendingBase&&!pendingBase.position){showRegion(pendingBase.regionId);startLocation(pendingBase);}else if(pendingId)sessionStorage.removeItem('military-pending-location-'+config.countryId);
        if (results.some(result=>result.status==='rejected')) { status.hidden=false; status.textContent='Nie udało się wczytać wszystkich warstw mapy.'; }
    }).catch(()=>{status.hidden=false;status.textContent='Nie udało się wyświetlić mapy.';});
    drawBases();drawMines();drawFactories();window.GameRadar?.draw();drawPower();
    updateFlights(config.flights,config.gameNow);drawShips();drawCargoShips();drawDefenses();
    const requested=Number(new URLSearchParams(location.search).get('base'));
    const requestedBase=config.bases.find(base=>base.id===requested);if(requestedBase&&config.mode==='defense')selectObject('base',requestedBase);
    map.on('click',event=>{if(locating)saveLocation(event.latlng);else if(redirecting){const request={action:'redirect_vessel',vessel_id:redirecting.id,x:event.latlng.lng,y:event.latlng.lat};modal('Zmienić kierunek okrętu?',()=>fields.append(make('p',`${vesselName(redirecting)} popłynie z obecnej pozycji do wskazanego punktu (${config.vesselSpeed} km/h Entendy).`)),()=>post(request));}else if(sailing){const request=sailing.kind==='carriers'?{action:'sail_carrier',base_id:sailing.base.id,...sailing.extra,x:event.latlng.lng,y:event.latlng.lat}:{action:'sail',base_id:sailing.base.id,vessel_kind:sailing.kind,x:event.latlng.lng,y:event.latlng.lat};modal('Wysłać okręt?',()=>fields.append(make('p',`Prędkość: ${config.vesselSpeed} km/h Entendy. Okręt popłynie do wskazanego punktu.`)),()=>post(request));}});
    setInterval(()=>{if(!document.hidden)refreshState();},5000);
    if(window.ResizeObserver)new ResizeObserver(()=>{map.invalidateSize({pan:false});if(framedRegion)fitRegion(framedRegion);}).observe(map.getContainer());
})();
