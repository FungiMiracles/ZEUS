/* Wojska lądowe na mapie obrony i wojny (11 Nov 2026): obrona miast, inwazja (przemarsz + bitwa), okupacja, aneksja.
   Moduł korzysta z API mapy wystawionego przez game_military.js (window.GameLandWar.init). */
(() => {
    'use strict';
    let api=null,cfg=null,layer=null,armies=[],occupations=[];
    const cityLayers=new Map(),marching=new Map();
    const UNITS=['soldiers','armored','tanks'];
    const UNIT_LABELS={soldiers:'Żołnierze',armored:'Wozy opancerzone',tanks:'Czołgi'};
    const lw=()=>cfg.landWar||{};
    const make=(...args)=>api.make(...args);
    const icon=(src,alt='')=>{const node=api.image(src,alt);node.className='land-icon';return node;};
    const money=value=>api.number(Math.round(Number(value)||0))+' ROI';
    const uuid=()=>crypto.randomUUID?crypto.randomUUID():'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g,c=>{const r=crypto.getRandomValues(new Uint8Array(1))[0]&15;return (c==='x'?r:(r&3)|8).toString(16);});
    const countryName=id=>cfg.countries[String(id)]||'Państwo';
    function flag(id){const node=make('span',null,'land-flag');const image=api.image(cfg.flags[String(id)]||'','');image.onerror=()=>image.remove();node.append(image,make('span',countryName(id)));return node;}
    function unitRows(units,parent){
        for(const unit of UNITS){const row=make('div',null,'land-unit-row');row.append(icon(lw().icons[unit]),make('span',UNIT_LABELS[unit]),make('strong',api.number(units?.[unit]||0)));parent.append(row);}
    }
    function sum(rows){const total={soldiers:0,armored:0,tanks:0};for(const row of rows)for(const unit of UNITS)total[unit]+=row.units[unit]||0;return total;}
    const occupation=(kind,id)=>occupations.find(o=>o.status==='ACTIVE'&&o.kind===kind&&Number(kind==='base'?o.baseId:kind==='city'?o.cityId:o.regionId)===Number(id));
    function occupationLabel(o){const node=make('div',null,'land-occupied-label');node.append(make('span','Okupowane przez:'),flag(o.occupierId));return node;}
    async function send(url,payload){
        const response=await fetch(url,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':cfg.csrf},body:JSON.stringify(payload)});
        const result=await response.json().catch(()=>({}));
        if(!response.ok)throw new Error(result.error||'Nie udało się zapisać zmian.');
        return result;
    }
    async function done(result){if(api.dialog.open)api.dialog.close();api.feedback(result.message||'Zapisano.');await api.refresh();}
    const ownLandBases=()=>(cfg.bases||[]).filter(base=>base.kind==='land'&&base.countryId===cfg.countryId&&base.position&&base.operational&&base.health>0&&!occupation('base',base.id));
    const holder=(kind,id,owner)=>occupation(kind,id)?.occupierId??owner;

    // ---------- miasta: karta po najechaniu ----------
    function cityCard(cityId,city){
        const card=make('div',null,'land-city-card');
        const title=make('div',null,'land-city-title');title.append(icon(lw().icons.city),make('strong',city.name));card.append(title);
        const occupied=occupation('city',cityId);
        if(occupied){card.append(occupationLabel(occupied));const army=sum(armies.filter(a=>a.status==='OCCUPYING'&&a.targetKind==='city'&&String(a.targetCityId)===cityId));unitRows(army,card);
            if(city.countryId===cfg.countryId)recaptureButton(card,'Odbij miasto',{kind:'city',id:Number(cityId),name:city.name,owner:city.countryId,point:city.point},occupied);
            if(occupied.occupierId===cfg.countryId)withdrawButton(card,occupied,city.name,ownOccupiers('city',cityId));
            return card;}
        if(city.countryId!==cfg.countryId)return card;
        const defenders=armies.filter(a=>a.status==='DEFENDING'&&String(a.targetCityId)===cityId&&a.countryId===cfg.countryId);
        if(defenders.length){card.append(make('p','Obrona miasta:','land-muted'));unitRows(sum(defenders),card);
            for(const army of defenders){const row=make('div',null,'land-detachment');const base=(cfg.bases||[]).find(b=>b.id===army.sourceBaseId);
                row.append(make('span',`Oddział z: ${base?api.baseName(base):'bazy #'+army.sourceBaseId}`));
                const back=make('button','Wycofaj','land-small-button');back.type='button';back.onclick=async()=>{back.disabled=true;try{await done(await send(lw().cityDefenseUrl,{action:'withdraw',army_id:army.id}));}catch(error){api.feedback(error.message);back.disabled=false;}};
                row.append(back);card.append(row);}
        }
        const add=make('button','Dodaj obronę wojska','land-button');add.type='button';add.onclick=()=>{api.map.closePopup();defenseModal(cityId,city);};card.append(add);
        return card;
    }
    function bindCity(marker,cityId,city){
        cityLayers.set(cityId,{marker,city});
        let timer=null,popup=null;
        const close=()=>{timer=setTimeout(()=>{if(popup)api.map.closePopup(popup);},280);};
        marker.on('mouseover',()=>{
            clearTimeout(timer);
            popup=L.popup({closeButton:false,autoPan:false,className:'land-city-popup',offset:[0,-4]}).setLatLng(marker.getLatLng()).setContent(cityCard(cityId,city)).openOn(api.map);
            const element=popup.getElement();if(element){element.addEventListener('mouseenter',()=>clearTimeout(timer));element.addEventListener('mouseleave',close);}
        });
        marker.on('mouseout',close);
        styleCity(cityId);
    }
    function styleCity(cityId){
        const entry=cityLayers.get(cityId);if(!entry?.marker.setStyle)return;
        const occupied=occupation('city',cityId);
        // 13 Nov 2026: na ekranach obrony i panelu wojennego miasta jak na mapie świata (białe z ciemną obwódką).
        entry.marker.setStyle(occupied?{color:'#ffd0d0',fillColor:'#c62828'}:{color:'#22301f',fillColor:'#FFFFFF'});
    }
    function defenseModal(cityId,city){
        // Only land bases in the city's own region can send its defenders.
        const bases=ownLandBases().filter(base=>String(base.regionId)===String(city.regionId));
        const available=base=>`żołnierze ${api.number(base.garrison?.soldiers||0)}, wozy opancerzone ${api.number(base.garrison?.armored||0)}, czołgi ${api.number(base.garrison?.tanks||0)}`;
        api.modal('Obrona miasta — '+city.name,()=>{
            if(!bases.length){api.fields.append(make('p',`W regionie ${cfg.regions[String(city.regionId)]?.name||'miasta'} nie ma sprawnej, własnej bazy lądowej na mapie, z której można wysłać wojsko.`));document.getElementById('military-dialog-confirm').disabled=true;return;}
            const source=api.choose('Baza wojskowa (lądowa) w regionie miasta','base_id',bases.map(base=>[base.id,`${api.baseName(base)} (${available(base)})`]));
            const inputs=Object.fromEntries(UNITS.map(unit=>[unit,api.input(UNIT_LABELS[unit],unit,0,0)]));
            const note=make('p',null,'land-muted');api.fields.append(note);
            const update=()=>{const base=bases.find(b=>b.id===Number(source.value));for(const unit of UNITS){inputs[unit].max=base?.garrison?.[unit]||0;inputs[unit].parentElement.firstChild.textContent=`${UNIT_LABELS[unit]} (do zabrania: ${api.number(base?.garrison?.[unit]||0)})`;}
                note.textContent='Żołnierze i sprzęt opuszczą bazę i będą bronić miasta.';};
            source.onchange=update;update();
        },async data=>{
            const payload={action:'add',city_id:Number(cityId),base_id:Number(data.get('base_id')),request_id:uuid()};
            for(const unit of UNITS)payload[unit]=Number(data.get(unit)||0);
            await done(await send(lw().cityDefenseUrl,payload));
        });
    }

    // ---------- odbicie własnego miasta / bazy (11 Nov 2026) ----------
    function recaptureReason(occupied){
        if(!cfg.enemyIds.includes(occupied.occupierId))return 'Odbicie wymaga trwającej wojny z okupantem.';
        if(!ownLandBases().length)return 'Potrzebna jest własna, sprawna i nieokupowana baza lądowa na mapie.';
        return '';
    }
    function recaptureButton(parent,label,target,occupied){
        const button=make('button',label,'land-button land-recapture');button.type='button';
        const reason=recaptureReason(occupied);button.disabled=!!reason;if(reason)button.title=reason;
        button.onclick=()=>{api.map.closePopup();chooseBase(target,true);};
        parent.append(button);if(reason)parent.append(make('p',reason,'land-muted'));
    }
    function hoverCard(marker,content,className){
        let timer=null,popup=null;
        const close=()=>{timer=setTimeout(()=>{if(popup)api.map.closePopup(popup);},280);};
        marker.on('mouseover',()=>{
            clearTimeout(timer);
            popup=L.popup({closeButton:false,autoPan:false,className,offset:[0,-14]}).setLatLng(marker.getLatLng()).setContent(content()).openOn(api.map);
            const element=popup.getElement();if(element){element.addEventListener('mouseenter',()=>clearTimeout(timer));element.addEventListener('mouseleave',close);}
        });
        marker.on('mouseout',close);
    }
    function bindBase(marker,base,tooltip){
        // Własna, okupowana baza: zamiast zwykłego tooltipa karta z przyciskiem „Odbij bazę”;
        // baza okupowana przez nasze wojska: karta z przyciskiem „Wycofaj wojsko”.
        const occupied=occupation('base',base.id);
        if(occupied&&occupied.occupierId===cfg.countryId&&base.position){
            hoverCard(marker,()=>{const card=make('div',null,'land-city-card');card.append(tooltip.cloneNode(true));
                withdrawButton(card,occupied,api.baseName(base),ownOccupiers('base',base.id));return card;},'land-city-popup');
            return true;
        }
        if(!occupied||base.countryId!==cfg.countryId||!base.position)return false;
        hoverCard(marker,()=>{const card=make('div',null,'land-city-card');card.append(tooltip.cloneNode(true));
            recaptureButton(card,'Odbij bazę',{kind:'base',id:base.id,name:api.baseName(base),owner:base.countryId,point:base.position},occupied);return card;},'land-city-popup');
        return true;
    }
    // ---------- wycofanie wojsk okupacyjnych ----------
    const ownOccupiers=(kind,id)=>sum(armies.filter(a=>a.status==='OCCUPYING'&&a.countryId===cfg.countryId&&a.targetKind===kind&&String(kind==='city'?a.targetCityId:a.targetBaseId)===String(id)));
    const withdrawBases=()=>(cfg.bases||[]).filter(base=>base.countryId===cfg.countryId&&['land','air','naval'].includes(base.kind)&&base.position&&base.operational&&base.health>0&&!occupation('base',base.id));
    function freeCapacity(base){
        const capacity=(lw().capacities?.[base.kind]||[])[base.level-1]||{};
        return Object.fromEntries(UNITS.map(unit=>[unit,Math.max(0,(capacity[unit]||0)-(base.garrison?.[unit]||0))]));
    }
    function withdrawButton(parent,occupied,name,present){
        const button=make('button','Wycofaj wojsko','land-button land-withdraw');button.type='button';
        const reason=!withdrawBases().length?'Potrzebna jest własna, sprawna i nieokupowana baza.':!(present.soldiers||present.armored||present.tanks)?'W obiekcie nie ma naszych wojsk.':'';
        button.disabled=!!reason;if(reason)button.title=reason;
        button.onclick=()=>{api.map.closePopup();withdrawModal(occupied,name,present);};
        parent.append(button);if(reason)parent.append(make('p',reason,'land-muted'));
    }
    function withdrawModal(occupied,name,present){
        const bases=withdrawBases();
        api.modal(`Wycofaj wojsko — ${name}`,()=>{
            api.fields.append(make('p',`W obiekcie: żołnierze ${api.number(present.soldiers)}, wozy opancerzone ${api.number(present.armored)}, czołgi ${api.number(present.tanks)}.`,'land-muted'));
            const select=api.choose('Baza, do której wrócą jednostki','base_id',bases.map(base=>[base.id,`${api.baseName(base)} — ${cfg.regions[base.regionId]?.name||''}`]));
            const room=make('p',null,'land-muted');api.fields.append(room);
            const inputs=Object.fromEntries(UNITS.map(unit=>[unit,api.input(UNIT_LABELS[unit],unit,0,present[unit]||0)]));
            const update=()=>{
                const base=bases.find(b=>b.id===Number(select.value));if(!base)return;
                const free=freeCapacity(base);
                for(const unit of UNITS){const limit=Math.min(present[unit]||0,free[unit]);inputs[unit].max=limit;if(Number(inputs[unit].value)>limit)inputs[unit].value=limit;inputs[unit].disabled=limit===0;}
                room.textContent=`Wolne miejsca w bazie: żołnierze ${api.number(free.soldiers)}, wozy ${api.number(free.armored)}, czołgi ${api.number(free.tanks)}`+(base.kind!=='land'?' (sprzęt pomieści tylko baza lądowa).':'.')+' Pozostałe jednostki zostaną w obiekcie.';
                document.getElementById('military-dialog-confirm').disabled=!UNITS.some(unit=>Number(inputs[unit].value)>0);
            };
            select.onchange=update;for(const input of Object.values(inputs))input.oninput=update;update();
        },async data=>{
            const payload={action:'withdraw',occupation_id:occupied.id,base_id:Number(data.get('base_id'))};
            for(const unit of UNITS)payload[unit]=Number(data.get(unit)||0);
            await done(await send(lw().occupationUrl,payload));
        });
    }

    const regionOccupied=id=>{const row=occupation('region',id);return !!row&&row.occupierId!==cfg.countryId;};

    // ---------- bazy: status okupacji ----------
    function baseTooltip(base,tooltip){
        const occupied=occupation('base',base.id);if(!occupied)return;
        tooltip.append(occupationLabel(occupied));
        const army=sum(armies.filter(a=>a.status==='OCCUPYING'&&a.targetKind==='base'&&a.targetBaseId===base.id));
        if(army.soldiers||army.armored||army.tanks){tooltip.append(make('p','Armia okupacyjna:','land-muted'));unitRows(army,tooltip);}
    }
    function baseSymbol(base,symbol){
        const occupied=occupation('base',base.id);if(!occupied)return;
        symbol.classList.add('land-occupied-symbol');const badge=api.image(cfg.flags[String(occupied.occupierId)]||'','');badge.className='land-occupied-flag';badge.onerror=()=>badge.remove();symbol.append(badge);
    }
    function regionTooltip(id,region){
        const node=make('div');node.append(make('span',region.name));
        const occupied=occupation('region',id);if(occupied){const label=make('div',null,'land-occupied-label');label.append(make('span','Okupowany przez:'),flag(occupied.occupierId));node.append(label);}
        return node;
    }

    // ---------- inwazja ----------
    function targetOf(context){
        const target=context.target;
        if(target?.kind==='base'){const base=(cfg.visibleBases||[]).find(b=>b.id===target.id);if(!base||!['land','naval','air'].includes(base.kind))return null;
            return {kind:'base',id:base.id,name:api.baseName(base),owner:base.countryId,point:base.position};}
        if(context.cityId&&!target){const city=cfg.cities[context.cityId];return city?{kind:'city',id:Number(context.cityId),name:city.name,owner:city.countryId,point:city.point}:null;}
        return null;
    }
    function warActions(actions,context){
        const target=targetOf(context);if(!target)return;
        const enemy=holder(target.kind,target.id,target.owner);
        if(enemy===cfg.countryId)return;
        const recapture=target.owner===cfg.countryId;
        const button=make('button','Wprowadź armię lądową','military-action military-attack');button.type='button';button.prepend(api.image(cfg.attackIcons.land));
        let reason='';
        if(!cfg.enemyIds.includes(enemy))reason='Wojska lądowe można wprowadzić tylko do państwa, z którym trwa wojna.';
        else if(!recapture&&!(lw().neighbors||[]).includes(enemy))reason='Atakowane państwo musi graniczyć z naszym państwem.';
        else if(!ownLandBases().length)reason='Potrzebna jest własna, sprawna baza lądowa na mapie.';
        button.disabled=!!reason;if(reason)button.title=reason;
        button.onclick=()=>chooseBase(target);
        actions.append(button);
        if(reason)actions.append(make('p',reason,'land-muted'));
    }
    function chooseBase(target,recapture=false){
        const bases=ownLandBases();
        api.modal((recapture?'Odbicie — wybierz bazę lądową: ':'Wybierz bazę lądową — przemarsz na: ')+target.name,()=>{
            api.choose('Baza lądowa, z której wyruszy armia','base_id',bases.map(base=>[base.id,`${api.baseName(base)} — ${cfg.regions[base.regionId]?.name||''} (żołnierze ${api.number(base.garrison.soldiers||0)}, wozy ${api.number(base.garrison.armored||0)}, czołgi ${api.number(base.garrison.tanks||0)})`]));
            api.fields.append(make('p','Najpierw wybierz bazę; w następnym kroku wskażesz liczbę żołnierzy i sprzętu.','land-muted'));
        },async data=>{const base=bases.find(b=>b.id===Number(data.get('base_id')));if(!base)throw new Error('Wybierz bazę lądową.');api.dialog.close();invasionModal(target,base,recapture);});
    }
    function invasionModal(target,base,recapture=false){
        const settings=lw();
        api.modal(`${recapture?(target.kind==='city'?'Odbij miasto':'Odbij bazę'):'Wprowadź armię lądową'} — ${target.name}`,()=>{
            api.fields.append(make('p',`Baza: ${api.baseName(base)} · wyszkolenie wojsk lądowych: ${settings.training} / 1000`,'land-muted'));
            const inputs=Object.fromEntries(UNITS.map(unit=>[unit,api.input(UNIT_LABELS[unit],unit,0,base.garrison?.[unit]||0)]));
            const quote=make('div',null,'land-quote');api.fields.append(quote);
            const update=()=>{
                const units=Object.fromEntries(UNITS.map(unit=>[unit,Math.max(0,Number(inputs[unit].value)||0)]));
                const extra=Number(settings.gdpPerCapita)*0.01;
                const cost=UNITS.reduce((total,unit)=>total+units[unit]*(Number(settings.unitCosts[unit])+extra),0);
                const distance=Math.hypot(target.point[0]-base.position[0],target.point[1]-base.position[1])*cfg.kmPerUnit;
                const speed=units.armored>0?settings.speeds.armored:settings.speeds.foot;
                quote.replaceChildren(make('p',`Koszt ${recapture?'odbicia':'inwazji'}: ${money(cost)} (z budżetu sił zbrojnych).`),
                    make('p',`Na jednostkę: żołnierz ${money(Number(settings.unitCosts.soldiers)+extra)}, wóz opancerzony ${money(Number(settings.unitCosts.armored)+extra)}, czołg ${money(Number(settings.unitCosts.tanks)+extra)} (w tym PKB per capita × 0,01).`),
                    make('p',`Odległość: ${distance.toLocaleString('pl-PL',{maximumFractionDigits:1})} km · prędkość: ${speed} km/h Entendy${units.armored>0?' (z wozami opancerzonymi)':''} · czas przemarszu: ${(distance/speed).toLocaleString('pl-PL',{maximumFractionDigits:1})} godz. Entendy.`));
                document.getElementById('military-dialog-confirm').disabled=!(units.soldiers||units.armored||units.tanks);
            };
            for(const input of Object.values(inputs))input.oninput=update;update();
        },async data=>{
            const payload={source_base_id:base.id,target_kind:target.kind,target_id:target.id,request_id:uuid()};
            for(const unit of UNITS)payload[unit]=Number(data.get(unit)||0);
            await done(await send(lw().invasionUrl,payload));
        });
    }

    // ---------- przemarsz: linia, ikona, tooltip ----------
    function armyTooltip(army){
        const node=make('div',null,'land-army-tooltip');node.append(flag(army.countryId));
        unitRows(army.units,node);
        node.append(make('p',`Prędkość: ${army.speedKmh} km/h Entendy`),make('p',`Cel: ${army.targetName}`),
                    make('p',`Dotarcie (Entenda): ${new Intl.DateTimeFormat('pl-PL',{timeZone:'UTC',dateStyle:'short',timeStyle:'short'}).format(new Date(army.arrivesAt))}`));
        return node;
    }
    function draw(){
        if(!layer)return;layer.clearLayers();marching.clear();
        for(const army of armies){
            if(army.status!=='MARCHING'||!army.source||!army.target)continue;
            const from=L.latLng(army.source[1],army.source[0]),to=L.latLng(army.target[1],army.target[0]);
            L.polyline([from,to],{color:'#d32f2f',weight:3,dashArray:'8 8',opacity:.9,interactive:false}).addTo(layer);
            const symbol=make('div',null,'land-invasion-symbol');symbol.append(api.image(lw().icons.invasion,'Armia lądowa'));
            const marker=L.marker(from,{icon:L.divIcon({html:symbol,className:'land-invasion-marker',iconSize:[34,34],iconAnchor:[17,17]}),zIndexOffset:2000}).bindTooltip(armyTooltip(army),{direction:'top',offset:[0,-16],className:'military-wrapping-tooltip'}).addTo(layer);
            marching.set(army.id,{army,marker,from,to});
        }
        for(const id of cityLayers.keys())styleCity(id);
    }
    function tick(now){
        for(const {army,marker,from,to} of marching.values()){
            const start=Date.parse(army.startsAt),end=Date.parse(army.arrivesAt);
            const f=end>start?Math.min(1,Math.max(0,(now-start)/(end-start))):1;
            marker.setLatLng(L.latLng(from.lat+(to.lat-from.lat)*f,from.lng+(to.lng-from.lng)*f));
        }
    }

    // ---------- okupowane regiony: siatka czerwonych linii ----------
    let regionGeometry=null,toLatLng=null,hatchLayer=null;
    function ensureHatchPattern(){
        const svg=api.map.getPanes().overlayPane.querySelector('svg');if(!svg||svg.querySelector('#land-occupation-hatch'))return;
        const ns='http://www.w3.org/2000/svg',defs=document.createElementNS(ns,'defs'),pattern=document.createElementNS(ns,'pattern');
        pattern.setAttribute('id','land-occupation-hatch');pattern.setAttribute('patternUnits','userSpaceOnUse');pattern.setAttribute('width','10');pattern.setAttribute('height','10');pattern.setAttribute('patternTransform','rotate(45)');
        for(const [x1,y1,x2,y2] of [[0,0,0,10],[0,0,10,0]]){const line=document.createElementNS(ns,'line');line.setAttribute('x1',x1);line.setAttribute('y1',y1);line.setAttribute('x2',x2);line.setAttribute('y2',y2);line.setAttribute('stroke','#c62828');line.setAttribute('stroke-width','1.6');pattern.append(line);}
        defs.append(pattern);svg.prepend(defs);
    }
    function drawOccupiedRegions(){
        if(!regionGeometry||!api)return;
        const ids=new Set(occupations.filter(o=>o.kind==='region'&&o.status==='ACTIVE').map(o=>String(o.regionId)));
        if(hatchLayer){hatchLayer.remove();hatchLayer=null;}
        if(!ids.size)return;
        hatchLayer=L.geoJSON(regionGeometry,{coordsToLatLng:toLatLng,interactive:false,filter:feature=>ids.has(String(feature.properties?.region_id)),
            style:{color:'#c62828',weight:2,opacity:.95,fill:true,fillColor:'url(#land-occupation-hatch)',fillOpacity:1,className:'land-occupied-region'}}).addTo(api.map);
        ensureHatchPattern();
    }

    // ---------- okupacja regionów: decyzja i aneksja ----------
    function renderOccupations(){
        const panel=document.getElementById('land-war-occupations');if(!panel)return;
        const mine=occupations.filter(o=>o.kind==='region'&&(o.occupierId===cfg.countryId||o.ownerId===cfg.countryId));
        panel.hidden=!mine.length;panel.replaceChildren();if(!mine.length)return;
        panel.append(make('h3','Okupacje regionów'));
        const now=api.currentGameTime();
        for(const row of mine){
            const item=make('div',null,'land-occupation-item');const region=cfg.regions[String(row.regionId)]?.name||('Region #'+row.regionId);
            if(row.occupierId===cfg.countryId){
                if(row.status==='PENDING'||row.status==='DECLINED'){
                    item.append(make('p',row.status==='PENDING'?`Zajęliśmy wszystkie bazy i miasta regionu ${region}. Czy prowadzić okupację regionu?`:`Region ${region}: wojska pozostają bez okupacji regionu.`));
                    const yes=make('button',row.status==='PENDING'?'Tak — okupuj region':'Rozpocznij okupację','land-button');yes.type='button';yes.onclick=()=>decide(row,true);item.append(yes);
                    if(row.status==='PENDING'){const no=make('button','Nie','land-small-button');no.type='button';no.onclick=()=>decide(row,false);item.append(no);}
                } else {
                    const ready=now>=Date.parse(row.annexAt);
                    item.append(make('p',`Region ${region} okupowany przez nasze państwo. Aneksja możliwa od: ${new Intl.DateTimeFormat('pl-PL',{timeZone:'UTC',dateStyle:'short',timeStyle:'short'}).format(new Date(row.annexAt))} (Entenda).`));
                    const annex=make('button','Anektuj region','land-button');annex.type='button';annex.disabled=!ready;if(!ready)annex.title=`Po ${lw().annexDays} dniach Entendy okupacji.`;
                    annex.onclick=()=>api.modal('Aneksja regionu '+region,()=>api.fields.append(make('p','Region zostanie wcielony do naszego państwa razem z miastami; okupowane bazy przejdą pod nasze dowództwo.')),
                        async()=>{await done(await send(lw().occupationUrl,{action:'annex',occupation_id:row.id}));});
                    item.append(annex);
                }
            } else if(row.status==='ACTIVE'){
                const text=make('p',null);text.append(make('span',`Region ${region} — okupowany przez: `),flag(row.occupierId),make('span',` · odbij go przed ${new Intl.DateTimeFormat('pl-PL',{timeZone:'UTC',dateStyle:'short'}).format(new Date(row.annexAt))}, inaczej okupant może go anektować.`));
                item.append(text);
            } else continue;
            panel.append(item);
        }
    }
    async function decide(row,occupy){try{await done(await send(lw().occupationUrl,{action:'decide',occupation_id:row.id,occupy}));}catch(error){api.feedback(error.message);}}
    function askPending(){
        const row=occupations.find(o=>o.kind==='region'&&o.status==='PENDING'&&o.occupierId===cfg.countryId);
        if(!row||api.dialog.open)return;
        const key='land-occupation-asked-'+row.id;try{if(sessionStorage.getItem(key))return;sessionStorage.setItem(key,'1');}catch{}
        const region=cfg.regions[String(row.regionId)]?.name||('Region #'+row.regionId);
        api.modal('Okupacja regionu '+region,()=>{
            api.fields.append(make('p',`Nasze wojska zajęły wszystkie bazy i miasta regionu ${region}. Czy chcesz prowadzić okupację regionu?`),
                make('p',`Jeśli tak, region przejdzie w status „Okupowany przez” nasze państwo; po ${lw().annexDays} dniach Entendy bez odbicia będzie można go anektować. Jeśli nie, wojska mogą zostać w regionie bez okupacji.`,'land-muted'));
            const no=make('button','Nie','land-small-button');no.type='button';no.onclick=async()=>{try{await done(await send(lw().occupationUrl,{action:'decide',occupation_id:row.id,occupy:false}));}catch(error){document.getElementById('military-dialog-error').textContent=error.message;}};
            api.fields.append(no);
        },async()=>{await done(await send(lw().occupationUrl,{action:'decide',occupation_id:row.id,occupy:true}));});
    }

    window.GameLandWar={
        init(context){api=context;cfg=context.config;armies=lw().armies||[];occupations=lw().occupations||[];layer=L.layerGroup().addTo(api.map);draw();renderOccupations();askPending();},
        update(state){if(!api)return;armies=state.armies||armies;occupations=state.occupations||occupations;draw();drawOccupiedRegions();renderOccupations();askPending();},
        setRegions(regions,coordinates){regionGeometry=regions;toLatLng=coordinates;drawOccupiedRegions();},
        bindCity,bindBase,regionOccupied,baseTooltip,baseSymbol,regionTooltip,warActions,tick,
    };
})();
