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
    // 23 Nov 2026: przed otwarciem okna z listą baz pobieramy świeży stan — lista nie może pokazywać baz zlikwidowanych
    // w innej karcie ani w czasie, gdy cykliczne odświeżanie (co 5 s) się nie powiodło.
    async function fresh(open){
        try{
            const response=await fetch(cfg.stateUrl,{credentials:'same-origin',cache:'no-store'});
            if(response.ok){const state=await response.json();if(Array.isArray(state.bases)){cfg.visibleBases=state.bases;cfg.bases=state.bases.filter(base=>base.countryId===cfg.countryId);}
                if(state.armies)armies=state.armies;if(state.occupations)occupations=state.occupations;}
        }catch{}
        open();
    }
    // 23 Nov 2026: pozycja listy baz lądowych — nazwa, region i stan garnizonu (okna inwazji, odbicia, wyzwolenia i „Dorzuć wojsko”)
    const baseOption=base=>[base.id,`${api.baseName(base)} — ${cfg.regions[base.regionId]?.name||''} (żołnierze ${api.number(base.garrison?.soldiers||0)}, wozy ${api.number(base.garrison?.armored||0)}, czołgi ${api.number(base.garrison?.tanks||0)})`];
    // 23 Nov 2026: obiekt sojusznika okupowany przez inne państwo — można go wyzwolić (wraca do sojusznika).
    const isAlly=id=>(cfg.allyIds||[]).includes(Number(id));
    const liberable=(owner,occupied)=>!!occupied&&isAlly(owner)&&occupied.occupierId!==cfg.countryId&&occupied.occupierId!==Number(owner);

    // ---------- miasta: karta po najechaniu (informacje) i opcje w kole na mapie (25 Nov 2026) ----------
    function cityCard(cityId,city){
        const card=make('div',null,'land-city-card');
        const title=make('div',null,'land-city-title');title.append(icon(lw().icons.city),make('strong',city.name));card.append(title);
        const occupied=occupation('city',cityId);
        if(occupied){card.append(occupationLabel(occupied));unitRows(sum(armies.filter(a=>a.status==='OCCUPYING'&&a.targetKind==='city'&&String(a.targetCityId)===cityId)),card);return card;}
        if(city.countryId!==cfg.countryId)return card;
        const defenders=armies.filter(a=>a.status==='DEFENDING'&&String(a.targetCityId)===cityId&&a.countryId===cfg.countryId);
        if(defenders.length){card.append(make('p','Obrona miasta:','land-muted'));unitRows(sum(defenders),card);
            for(const army of defenders){const base=(cfg.bases||[]).find(b=>b.id===army.sourceBaseId);
                card.append(make('div',base?`Oddział z: ${api.baseName(base)}`:army.sourceBaseId?`Oddział z: bazy #${army.sourceBaseId}`:'Oddział bez bazy macierzystej','land-detachment'));}
        }
        return card;
    }
    function cityActions(cityId,parent){
        const city=cfg.cities[cityId];if(!city)return;
        const occupied=occupation('city',cityId);
        if(occupied){
            if(city.countryId===cfg.countryId)recaptureButton(parent,'Odbij miasto',{kind:'city',id:Number(cityId),name:city.name,owner:city.countryId,point:city.point},occupied);
            else if(liberable(city.countryId,occupied))recaptureButton(parent,'Wyzwól miasto',{kind:'city',id:Number(cityId),name:city.name,owner:city.countryId,point:city.point,liberate:true},occupied);
            if(occupied.occupierId===cfg.countryId){withdrawButton(parent,occupied,city.name,ownOccupiers('city',cityId));reinforceButton(parent,{kind:'city',id:Number(cityId),name:city.name,point:city.point});}
            return;
        }
        if(city.countryId!==cfg.countryId)return;
        const add=make('button','Dodaj obronę wojska','land-button');add.type='button';add.onclick=()=>fresh(()=>defenseModal(cityId,city));parent.append(add);
        const defenders=armies.filter(a=>a.status==='DEFENDING'&&String(a.targetCityId)===cityId&&a.countryId===cfg.countryId);
        defenders.forEach((army,index)=>{
            const base=(cfg.bases||[]).find(b=>b.id===army.sourceBaseId),units=army.units||{};
            // 23 Nov 2026: wycofanie do wybranej bazy albo do rezerwy państwa, także częściowe
            const back=make('button',defenders.length>1?`Wycofaj oddział ${index+1}`:'Wycofaj obronę wojska','land-small-button');back.type='button';
            back.title=`${base?`Oddział z: ${api.baseName(base)}`:army.sourceBaseId?`Oddział z: bazy #${army.sourceBaseId}`:'Oddział bez bazy macierzystej'} — żołnierze ${api.number(units.soldiers||0)}, wozy ${api.number(units.armored||0)}, czołgi ${api.number(units.tanks||0)}`;
            back.onclick=()=>fresh(()=>{const current=armies.find(a=>a.id===army.id&&a.status==='DEFENDING');if(current)defenseWithdrawModal(current,city.name);else api.feedback('Oddział nie broni już tego miasta.');});
            parent.append(back);
        });
    }
    function bindCity(marker,cityId,city){
        cityLayers.set(cityId,{marker,city});
        let timer=null,popup=null;
        const close=()=>{timer=setTimeout(()=>{if(popup)api.map.closePopup(popup);},280);};
        marker.on('mouseover',()=>{
            clearTimeout(timer);if(window.GameRadialMenu?.isOpen())return;
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
    function recaptureReason(occupied,liberate=false){
        if(!cfg.enemyIds.includes(occupied.occupierId))return liberate?'Wyzwolenie wymaga trwającej wojny z okupantem.':'Odbicie wymaga trwającej wojny z okupantem.';
        if(!ownLandBases().length)return 'Potrzebna jest własna, sprawna i nieokupowana baza lądowa na mapie.';
        return '';
    }
    function recaptureButton(parent,label,target,occupied){
        const button=make('button',label,'land-button land-recapture');button.type='button';
        const reason=recaptureReason(occupied,!!target.liberate);button.disabled=!!reason;if(reason)button.title=reason;
        button.onclick=()=>{api.map.closePopup();fresh(()=>chooseBase(target,true));};
        parent.append(button);if(reason)parent.append(make('p',reason,'land-muted'));
    }
    // 25 Nov 2026: operacje na okupowanej bazie (odbicie, wyzwolenie, wycofanie wojsk, posiłki) — w kole opcji na mapie.
    function baseActions(base,parent){
        const occupied=occupation('base',base.id);if(!occupied||!base.position)return;
        if(occupied.occupierId===cfg.countryId){withdrawButton(parent,occupied,api.baseName(base),ownOccupiers('base',base.id));reinforceButton(parent,{kind:'base',id:base.id,name:api.baseName(base),point:base.position});return;}
        if(liberable(base.countryId,occupied)){recaptureButton(parent,'Wyzwól bazę',{kind:'base',id:base.id,name:api.baseName(base),owner:base.countryId,point:base.position,liberate:true},occupied);return;}
        if(base.countryId===cfg.countryId)recaptureButton(parent,'Odbij bazę',{kind:'base',id:base.id,name:api.baseName(base),owner:base.countryId,point:base.position},occupied);
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
        button.onclick=()=>{api.map.closePopup();fresh(()=>withdrawModal(occupied,name,present));};
        parent.append(button);if(reason)parent.append(make('p',reason,'land-muted'));
    }
    // ---------- posiłki do okupowanego obiektu (22 Nov 2026) ----------
    function reinforceButton(parent,target){
        const button=make('button','Dorzuć wojsko','land-button land-reinforce');button.type='button';
        const reason=!ownLandBases().length?'Potrzebna jest własna, sprawna i nieokupowana baza lądowa na mapie.':'';
        button.disabled=!!reason;if(reason)button.title=reason;
        button.onclick=()=>{api.map.closePopup();fresh(()=>reinforceModal(target));};
        parent.append(button);if(reason)parent.append(make('p',reason,'land-muted'));
    }
    function reinforceModal(target){
        const bases=ownLandBases(),settings=lw();
        api.modal(`Dorzuć wojsko — ${target.name}`,()=>{
            api.fields.append(make('p','Wybrane jednostki pomaszerują z bazy lądowej do okupowanego obiektu i po dotarciu dołączą do wojsk okupacyjnych.','land-muted'));
            const select=api.choose('Baza lądowa, z której wyruszą jednostki','base_id',bases.map(baseOption));
            const room=make('p',null,'land-muted');api.fields.append(room);
            const inputs=Object.fromEntries(UNITS.map(unit=>[unit,api.input(UNIT_LABELS[unit],unit,0,0)]));
            const quote=make('div',null,'land-quote');api.fields.append(quote);
            const update=()=>{
                const base=bases.find(b=>b.id===Number(select.value));if(!base)return;
                for(const unit of UNITS){const limit=base.garrison?.[unit]||0;inputs[unit].max=limit;if(Number(inputs[unit].value)>limit)inputs[unit].value=limit;inputs[unit].disabled=limit===0;}
                room.textContent=`W bazie: żołnierze ${api.number(base.garrison?.soldiers||0)}, wozy opancerzone ${api.number(base.garrison?.armored||0)}, czołgi ${api.number(base.garrison?.tanks||0)}.`;
                const units=Object.fromEntries(UNITS.map(unit=>[unit,Math.max(0,Number(inputs[unit].value)||0)]));
                const extra=Number(settings.gdpPerCapita)*0.01;
                const cost=UNITS.reduce((total,unit)=>total+units[unit]*(Number(settings.unitCosts[unit])+extra),0);
                const distance=Math.hypot(target.point[0]-base.position[0],target.point[1]-base.position[1])*cfg.kmPerUnit;
                const speed=units.armored>0?settings.speeds.armored:settings.speeds.foot;
                quote.replaceChildren(make('p',`Koszt przemarszu: ${money(cost)} (z budżetu sił zbrojnych).`),
                    make('p',`Odległość: ${distance.toLocaleString('pl-PL',{maximumFractionDigits:1})} km · prędkość: ${speed} km/h Entendy${units.armored>0?' (z wozami opancerzonymi)':''} · czas przemarszu: ${(distance/speed).toLocaleString('pl-PL',{maximumFractionDigits:1})} godz. Entendy.`));
                document.getElementById('military-dialog-confirm').disabled=!(units.soldiers||units.armored||units.tanks);
            };
            select.onchange=update;for(const input of Object.values(inputs))input.oninput=update;update();
        },async data=>{
            const payload={source_base_id:Number(data.get('base_id')),target_kind:target.kind,target_id:target.id,reinforce:true,request_id:uuid()};
            for(const unit of UNITS)payload[unit]=Number(data.get(unit)||0);
            await done(await send(lw().invasionUrl,payload));
        });
    }
    function withdrawModal(occupied,name,present){
        const bases=withdrawBases();
        api.modal(`Wycofaj wojsko — ${name}`,()=>{
            api.fields.append(make('p',`W obiekcie: żołnierze ${api.number(present.soldiers)}, wozy opancerzone ${api.number(present.armored)}, czołgi ${api.number(present.tanks)}.`,'land-muted'));
            const select=api.choose('Baza, do której wrócą jednostki','base_id',bases.map(baseOption));
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

    // 23 Nov 2026: wycofanie obrony miasta — baza macierzysta (na początku listy), inna własna baza z wolnym miejscem
    // albo rezerwa państwa (jednostki bez przydziału); wycofać można też część oddziału.
    function defenseWithdrawModal(army,cityName){
        const present=army.units||{};
        const bases=withdrawBases().sort((a,b)=>(b.id===army.sourceBaseId)-(a.id===army.sourceBaseId));
        api.modal(`Wycofaj obronę — ${cityName}`,()=>{
            api.fields.append(make('p',`Oddział: żołnierze ${api.number(present.soldiers||0)}, wozy opancerzone ${api.number(present.armored||0)}, czołgi ${api.number(present.tanks||0)}.`,'land-muted'));
            const select=api.choose('Dokąd wrócą jednostki','base_id',[...bases.map(baseOption),['reserve','Rezerwa państwa — bez przydziału do bazy']]);
            const room=make('p',null,'land-muted');api.fields.append(room);
            const inputs=Object.fromEntries(UNITS.map(unit=>[unit,api.input(UNIT_LABELS[unit],unit,0,present[unit]||0)]));
            for(const unit of UNITS)inputs[unit].value=present[unit]||0;
            const update=()=>{
                const reserve=select.value==='reserve',base=bases.find(b=>b.id===Number(select.value));
                const free=reserve||!base?null:freeCapacity(base);
                for(const unit of UNITS){const limit=free?Math.min(present[unit]||0,free[unit]):(present[unit]||0);inputs[unit].max=limit;if(Number(inputs[unit].value)>limit)inputs[unit].value=limit;inputs[unit].disabled=limit===0;}
                room.textContent=free?`Wolne miejsca w bazie: żołnierze ${api.number(free.soldiers)}, wozy ${api.number(free.armored)}, czołgi ${api.number(free.tanks)}`+(base.kind!=='land'?' (sprzęt pomieści tylko baza lądowa).':'.')+' Pozostałe jednostki nadal bronią miasta.'
                    :'Jednostki wrócą do rezerwy państwa (bez przydziału do bazy); można je później przydzielić do dowolnej bazy.';
                document.getElementById('military-dialog-confirm').disabled=!UNITS.some(unit=>Number(inputs[unit].value)>0);
            };
            select.onchange=update;for(const input of Object.values(inputs))input.oninput=update;update();
        },async data=>{
            const payload={action:'withdraw',army_id:army.id};
            if(data.get('base_id')==='reserve')payload.to_reserve=true;else payload.base_id=Number(data.get('base_id'));
            for(const unit of UNITS)payload[unit]=Number(data.get(unit)||0);
            await done(await send(lw().cityDefenseUrl,payload));
        });
    }
    const regionOccupied=id=>{const row=occupation('region',id);return !!row&&row.occupierId!==cfg.countryId;};
    const regionUnderOccupation=id=>!!occupation('region',id);   // 22 Nov 2026: dowolna aktywna okupacja regionu (podświetlenie na czerwono)

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
        const occupied=occupation('region',id);if(occupied){const label=make('div',null,'land-occupied-label');label.append(make('span','Okupowany przez:'),flag(occupied.occupierId));node.append(label);
            const countdown=annexCountdown(occupied);if(countdown)node.append(make('div',countdown,'land-annex-countdown'));}
        return node;
    }
    // Czas do aneksji okupowanego regionu (22 Nov 2026): czas Entendy i jego odpowiednik w czasie rzeczywistym.
    function durationText(ms){
        const minutes=Math.max(1,Math.ceil(ms/6e4)),d=Math.floor(minutes/1440),h=Math.floor(minutes%1440/60),m=minutes%60;
        const parts=[];if(d)parts.push(d+' d');if(h)parts.push(h+' godz.');if(m&&!d)parts.push(m+' min');return parts.join(' ');
    }
    function annexCountdown(row){
        const at=Date.parse(row.annexAt);if(!Number.isFinite(at))return '';
        const left=at-api.currentGameTime();
        if(left<=0)return row.occupierId===cfg.countryId?'Aneksja możliwa — region można już anektować.':'Aneksja możliwa — okupant może już anektować region.';
        const real=left/(Number(cfg.timeMultiplier)||1);
        return `Do aneksji: ${durationText(left)} Entendy (ok. ${durationText(real)} w czasie rzeczywistym)`;
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
        button.onclick=()=>fresh(()=>chooseBase(target));
        actions.append(button);
        if(reason)actions.append(make('p',reason,'land-muted'));
    }
    function chooseBase(target,recapture=false){
        const bases=ownLandBases();
        api.modal((target.liberate?'Wyzwolenie — wybierz bazę lądową: ':recapture?'Odbicie — wybierz bazę lądową: ':'Wybierz bazę lądową — przemarsz na: ')+target.name,()=>{
            api.choose('Baza lądowa, z której wyruszy armia','base_id',bases.map(baseOption));
            api.fields.append(make('p','Najpierw wybierz bazę; w następnym kroku wskażesz liczbę żołnierzy i sprzętu.','land-muted'));
        },async data=>{const base=bases.find(b=>b.id===Number(data.get('base_id')));if(!base)throw new Error('Wybierz bazę lądową.');api.dialog.close();invasionModal(target,base,recapture);});
    }
    function invasionModal(target,base,recapture=false){
        const settings=lw();
        api.modal(`${target.liberate?(target.kind==='city'?'Wyzwól miasto':'Wyzwól bazę'):recapture?(target.kind==='city'?'Odbij miasto':'Odbij bazę'):'Wprowadź armię lądową'} — ${target.name}`,()=>{
            if(target.liberate)api.fields.append(make('p',`Po zwycięstwie obiekt wróci do sojusznika (${countryName(target.owner)}), a armia wróci do swojej bazy.`,'land-muted'));
            api.fields.append(make('p',`Baza: ${api.baseName(base)} · wyszkolenie wojsk lądowych: ${settings.training} / 1000`,'land-muted'));
            const inputs=Object.fromEntries(UNITS.map(unit=>[unit,api.input(UNIT_LABELS[unit],unit,0,base.garrison?.[unit]||0)]));
            const quote=make('div',null,'land-quote');api.fields.append(quote);
            const update=()=>{
                const units=Object.fromEntries(UNITS.map(unit=>[unit,Math.max(0,Number(inputs[unit].value)||0)]));
                const extra=Number(settings.gdpPerCapita)*0.01;
                const cost=UNITS.reduce((total,unit)=>total+units[unit]*(Number(settings.unitCosts[unit])+extra),0);
                const distance=Math.hypot(target.point[0]-base.position[0],target.point[1]-base.position[1])*cfg.kmPerUnit;
                const speed=units.armored>0?settings.speeds.armored:settings.speeds.foot;
                quote.replaceChildren(make('p',`Koszt ${target.liberate?'wyzwolenia':recapture?'odbicia':'inwazji'}: ${money(cost)} (z budżetu sił zbrojnych).`),
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
    // 22 Nov 2026: wroga armia maszerująca po naszym terytorium — można ją zaatakować (kliknięcie ikony armii).
    const attackable=army=>army.status==='MARCHING'&&army.role==='invasion'&&army.countryId!==cfg.countryId&&army.targetCountryId===cfg.countryId&&cfg.enemyIds.includes(army.countryId)&&Date.parse(army.arrivesAt)>api.currentGameTime();
    function draw(){
        if(!layer)return;layer.clearLayers();marching.clear();
        for(const army of armies){
            if(!['MARCHING','RETURNING'].includes(army.status)||!army.source||!army.target)continue;
            const from=L.latLng(army.source[1],army.source[0]),to=L.latLng(army.target[1],army.target[0]);
            const interceptor=army.role==='intercept',returning=army.status==='RETURNING';
            L.polyline([from,to],{color:returning?'#6b7a89':interceptor?'#1565c0':'#d32f2f',weight:3,dashArray:'8 8',opacity:.9,interactive:false}).addTo(layer);
            const symbol=make('div',null,'land-invasion-symbol'+(interceptor?' land-intercept-symbol':''));symbol.append(api.image(lw().icons.invasion,'Armia lądowa'));api.ownerFlag?.(symbol,army.countryId);
            const tooltip=armyTooltip(army);
            if(returning){symbol.classList.add('land-returning-symbol');tooltip.querySelector('p:nth-of-type(2)')?.replaceWith(make('p',`Powrót do bazy (przemarsz anulowany; cel był: ${army.targetName})`));}
            if(attackable(army)){symbol.classList.add('land-attackable');tooltip.append(make('p','Kliknij, aby zaatakować armię.','land-attack-hint'));}
            const marker=L.marker(from,{icon:L.divIcon({html:symbol,className:'land-invasion-marker',iconSize:[34,34],iconAnchor:[17,17]}),zIndexOffset:2000}).addTo(layer);
            marker.bindTooltip(tooltip,{direction:'top',offset:[0,-16],className:'military-wrapping-tooltip'});
            // 25 Nov 2026: własna armia w marszu — „Anuluj przemarsz” w kole opcji po kliknięciu ikony armii.
            if(army.countryId===cfg.countryId&&army.status==='MARCHING'&&lw().cancelMarchUrl)marker.on('click',event=>{L.DomEvent.stopPropagation(event);marker.closeTooltip();
                api.menu?.(`army:${army.id}`,marker.getLatLng(),parent=>cancelButton(parent,army),'Opcje armii w marszu');});
            // 25 Nov 2026: sposoby ataku na wrogą armię w kole dookoła armii (czerwone ikony); bez menu — dawne okno wyboru.
            if(attackable(army))marker.on('click',event=>{L.DomEvent.stopPropagation(event);marker.closeTooltip();
                if(!api.menu?.(`army:${army.id}`,marker.getLatLng(),parent=>attackMethods(army,parent),'Atak na armię: '+countryName(army.countryId)))attackArmy(army);});
            marching.set(army.id,{army,marker,from,to});
        }
        for(const id of cityLayers.keys())styleCity(id);
    }
    function tick(now){
        for(const {army,marker,from,to} of marching.values()){
            const start=Date.parse(army.startsAt),end=Date.parse(army.arrivesAt);
            const f=end>start?Math.min(1,Math.max(0,(now-start)/(end-start))):1;
            const point=L.latLng(from.lat+(to.lat-from.lat)*f,from.lng+(to.lng-from.lng)*f);marker.setLatLng(point);window.GameRadialMenu?.follow(`army:${army.id}`,point);
        }
    }

    function cancelButton(card,army){
        const button=make('button','Anuluj przemarsz','land-button land-cancel-march');button.type='button';
        button.title='Armia zawróci do bazy; powrót potrwa tyle, ile dotychczasowy marsz. Koszt inwazji nie jest zwracany.';
        button.onclick=async()=>{if(!confirm('Anulować przemarsz tej armii? Armia zawróci do bazy macierzystej. Powrót potrwa tyle, ile dotychczasowy marsz; koszt inwazji nie jest zwracany.'))return;button.disabled=true;
            try{await done(await send(lw().cancelMarchUrl,{army_id:army.id}));}catch(error){api.feedback(error.message);button.disabled=false;}};
        card.append(button);
    }
    // ---------- atak na wrogą armię w marszu (22 Nov 2026) ----------
    function armyPoint(army,moment){
        const start=Date.parse(army.startsAt),end=Date.parse(army.arrivesAt);
        const f=end>start?Math.min(1,Math.max(0,(moment-start)/(end-start))):1;
        return [army.source[0]+(army.target[0]-army.source[0])*f,army.source[1]+(army.target[1]-army.source[1])*f];
    }
    // Najwcześniejsze spotkanie (godz. Entendy od teraz) jednostki z punktu `from` (km/h) z armią; null — armia dotrze do celu wcześniej.
    function meeting(from,army,kmh){
        const now=api.currentGameTime(),left=(Date.parse(army.arrivesAt)-now)/36e5;
        const reach=h=>{const p=armyPoint(army,now+h*36e5);return Math.hypot(p[0]-from[0],p[1]-from[1])*cfg.kmPerUnit<=h*kmh;};
        if(left<=0||!reach(left))return null;
        let lo=0,hi=left;for(let i=0;i<40;i++){const mid=(lo+hi)/2;if(reach(mid))hi=mid;else lo=mid;}
        const point=armyPoint(army,now+hi*36e5);return {hours:hi,km:Math.hypot(point[0]-from[0],point[1]-from[1])*cfg.kmPerUnit};
    }
    const hoursText=h=>h.toLocaleString('pl-PL',{maximumFractionDigits:2})+' godz. Entendy';
    function attackMethods(army,parent,inDialog=false){
        for(const [kind,label] of ARMY_ATTACKS){
            const reason=methodReason(kind);
            const button=make('button',label,'military-action military-attack');button.type='button';button.prepend(api.image(cfg.attackIcons[kind]));
            button.disabled=!!reason;if(reason)button.title=reason;
            button.onclick=()=>{if(api.dialog.open)api.dialog.close();kind==='land'?fresh(()=>interceptModal(army)):strikeModal(army,kind,label);};
            parent.append(button);if(reason&&inDialog)parent.append(make('p',reason,'land-muted'));
        }
    }
    const ARMY_ATTACKS=[['air','Bombarduj z powietrza'],['missile','Wystrzel rakiety z własnego terytorium'],['naval','Zaatakuj z okrętu'],['land','Wyślij armię lądową']];
    function attackArmy(army){
        api.modal('Atak na armię w marszu — '+countryName(army.countryId),()=>{
            const info=make('div',null,'land-army-tooltip');info.append(flag(army.countryId));unitRows(army.units,info);
            info.append(make('p',`Cel armii: ${army.targetName} · dotarcie: ${new Intl.DateTimeFormat('pl-PL',{timeZone:'UTC',dateStyle:'short',timeStyle:'short'}).format(new Date(army.arrivesAt))} (Entenda)`,'land-muted'));
            api.fields.append(info,make('p','Wybierz sposób ataku:'));
            const list=make('div',null,'land-attack-methods');attackMethods(army,list,true);
            api.fields.append(list);
            document.getElementById('military-dialog-confirm').hidden=true;
            api.dialog.addEventListener('close',()=>{document.getElementById('military-dialog-confirm').hidden=false;},{once:true});
        },async()=>{});
    }
    const strikeShips=()=>(cfg.vessels||[]).filter(v=>v.countryId===cfg.countryId&&v.status!=='returning'&&v.health>0&&v.kind!=='carriers');
    const strikeCarriers=()=>(cfg.vessels||[]).filter(v=>v.countryId===cfg.countryId&&v.kind==='carriers'&&v.status!=='returning'&&v.health>0&&(v.fighters||0)-(v.busyFighters||0)>0);
    function methodReason(kind){
        if(kind==='land')return ownLandBases().length?'':'Potrzebna jest własna, sprawna baza lądowa na mapie.';
        if(kind==='naval')return strikeShips().length?'':'Wyślij okręt wojenny z bazy morskiej na mapę.';
        if(kind==='air')return api.sourceBases('air').length||strikeCarriers().length?'':'Potrzebna jest baza powietrzna z myśliwcami albo lotniskowiec na morzu.';
        return api.sourceBases('missile').length?'':'Potrzebna jest baza lądowa z wyrzutniami rakiet.';
    }
    function strikeModal(army,kind,label){
        const sources=api.sourceBases(kind),ships=strikeShips(),carriers=kind==='air'?strikeCarriers():[];
        api.modal(label+' — armia '+countryName(army.countryId),()=>{
            const options=kind==='naval'?ships.map(v=>[v.id,api.vesselName(v)]):sources.map(base=>[base.id,`${api.baseName(base)} — ${cfg.regions[base.regionId]?.name||''}`]).concat(carriers.map(v=>['c'+v.id,`${api.vesselName(v)} — myśliwce: ${(v.fighters||0)-(v.busyFighters||0)}/${v.fighters}`]));
            const source=api.choose(kind==='naval'?'Okręt':kind==='air'?'Baza powietrzna lub lotniskowiec':'Baza startowa',kind==='naval'?'vessel_id':'source_base_id',options);source.required=true;
            const missile=api.choose('Rodzaj rakiet','missile_type',Object.entries(cfg.missiles).map(([code,item])=>[code,`${item.label} — zapas: ${api.number(item.count)}`]));
            const quantity=api.input('Liczba rakiet','missiles',1,cfg.maxSalvo);quantity.min='1';
            const loss=lw().strikeLoss||[1,3];
            api.fields.append(make('p',`Każda trafiona rakieta niszczy od ${loss[0]} do ${loss[1]}% każdego rodzaju jednostek armii (żołnierze, wozy opancerzone, czołgi). Punkt trafienia jest wyliczany na trasie marszu.`,'land-muted'));
            const quote=make('p');api.fields.append(quote);
            const update=()=>{
                const fromCarrier=String(source.value).startsWith('c');
                const origin=fromCarrier?carriers.find(v=>'c'+v.id===source.value):kind==='naval'?ships.find(v=>v.id===Number(source.value)):sources.find(base=>base.id===Number(source.value));
                if(!origin){quote.textContent='Wybierz źródło ataku.';return;}
                const position=kind==='naval'||fromCarrier?api.shipPosition(origin,api.currentGameTime()):origin.position;
                const rule=cfg.missileRules[missile.value],kmh=kind==='air'?cfg.fighterSpeed:rule.speed;
                quantity.max=Math.min(cfg.maxSalvo,cfg.missiles[missile.value].count);
                const hit=position&&meeting(position,army,kmh);
                let invalid=!hit;
                if(!hit)quote.textContent='Armia dotrze do celu, zanim atak ją dosięgnie.';
                else{
                    invalid=kind==='air'?hit.km>cfg.fighterRange+1e-6:(hit.km<rule.min-1e-6||hit.km>rule.max+1e-6);
                    quote.textContent=`Odległość do punktu trafienia: ${hit.km.toLocaleString('pl-PL',{maximumFractionDigits:1})} km. Czas do trafienia: ${hoursText(hit.hours)}. `+(kind==='air'?`Zasięg myśliwca: ${cfg.fighterRange} km.`:`Zasięg rakiety: ${rule.min}–${rule.max} km.`);
                }
                quote.classList.toggle('military-range-error',invalid);document.getElementById('military-dialog-confirm').disabled=invalid;
            };
            // Na start: pierwszy rodzaj rakiet (z zapasem), którego zasięg obejmuje punkt trafienia.
            const pick=()=>{if(kind==='air')return;const origin=kind==='naval'?ships.find(v=>v.id===Number(source.value)):sources.find(base=>base.id===Number(source.value));const position=origin&&(kind==='naval'?api.shipPosition(origin,api.currentGameTime()):origin.position);if(!position)return;
                for(const [code,rule] of Object.entries(cfg.missileRules)){if(!(cfg.missiles[code]?.count>0))continue;const hit=meeting(position,army,rule.speed);if(hit&&hit.km>=rule.min-1e-6&&hit.km<=rule.max+1e-6){missile.value=code;return;}}};
            source.onchange=()=>{pick();update();};missile.onchange=update;pick();update();
        },async data=>{
            const carrierChoice=kind==='air'&&String(data.get('source_base_id')).startsWith('c');
            const payload={kind,target_army_id:army.id,region_id:army.targetRegionId,is_nuclear:false,missile_type:data.get('missile_type'),missiles:Number(data.get('missiles'))};
            if(kind==='naval'){const vessel=ships.find(v=>v.id===Number(data.get('vessel_id')));payload.vessel_id=vessel.id;payload.source_base_id=vessel.baseId;}
            else if(carrierChoice)payload.carrier_id=Number(String(data.get('source_base_id')).slice(1));
            else payload.source_base_id=Number(data.get('source_base_id'));
            await done(await send(cfg.orderUrl,payload));
        });
    }
    function interceptModal(army){
        const bases=ownLandBases();
        api.modal('Wyślij armię lądową — przechwycenie armii '+countryName(army.countryId),()=>{
            const source=api.choose('Baza lądowa, z której wyruszy oddział','source_base_id',bases.map(baseOption));
            const inputs=Object.fromEntries(UNITS.map(unit=>[unit,api.input(UNIT_LABELS[unit],unit,0,0)]));
            api.fields.append(make('p',`Oddział wyrusza do punktu spotkania na trasie marszu. Bitwa jak przy inwazji: siła = (żołnierze + 3 × wozy + 5 × czołgi) × wyszkolenie / 100 × (1 + los 0–0,5); remis wygrywa nasz oddział (obrona własnego terytorium). Przegrany traci całą armię; zwycięski oddział wraca do bazy. Bez opłaty inwazyjnej.`,'land-muted'));
            const quote=make('p');api.fields.append(quote);
            const update=()=>{
                const base=bases.find(b=>b.id===Number(source.value));
                for(const unit of UNITS){inputs[unit].max=base?.garrison?.[unit]||0;if(Number(inputs[unit].value)>Number(inputs[unit].max))inputs[unit].value=inputs[unit].max;}
                const units=Object.fromEntries(UNITS.map(unit=>[unit,Math.max(0,Number(inputs[unit].value)||0)]));
                const kmh=units.armored>0?lw().speeds.armored:lw().speeds.foot;
                const hit=base&&meeting(base.position,army,kmh);
                quote.textContent=!base?'Wybierz bazę.':!hit?`Oddział z tej bazy (${kmh} km/h) nie zdąży dogonić armii przed jej dotarciem do celu.`
                    :`Dostępne w bazie: żołnierze ${api.number(base.garrison?.soldiers||0)}, wozy ${api.number(base.garrison?.armored||0)}, czołgi ${api.number(base.garrison?.tanks||0)}. Prędkość: ${kmh} km/h · droga do punktu spotkania: ${hit.km.toLocaleString('pl-PL',{maximumFractionDigits:1})} km · bitwa za ${hoursText(hit.hours)}.`;
                quote.classList.toggle('military-range-error',!hit);
                document.getElementById('military-dialog-confirm').disabled=!hit||!(units.soldiers||units.armored||units.tanks);
            };
            source.onchange=update;for(const input of Object.values(inputs))input.oninput=update;update();
        },async data=>{
            const payload={army_id:army.id,source_base_id:Number(data.get('source_base_id')),request_id:uuid()};
            for(const unit of UNITS)payload[unit]=Number(data.get(unit)||0);
            await done(await send(lw().interceptUrl,payload));
        });
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
                    // 23 Nov 2026: region anektowany wcześniej z innego państwa — zamiast aneksji można go przywrócić (albo wskrzesić państwo)
                    if(row.restore){
                        const target=row.restore,label=target.resurrect?`Wskrześ państwo: ${target.name}`:`Przywróć państwu: ${target.name}`;
                        const restore=make('button',label,'land-button land-restore');restore.type='button';restore.disabled=!ready;if(!ready)restore.title=`Po ${lw().annexDays} dniach Entendy okupacji.`;
                        restore.onclick=()=>api.modal((target.resurrect?`Wskrzeszenie państwa ${target.name} — region `:'Przywrócenie regionu ')+region,()=>{
                            api.fields.append(make('p',target.resurrect
                                ?`Państwo ${target.name} odzyska niepodległość w regionie ${region}: stolica powstanie w największym mieście regionu, państwo przyjmie dawną nazwę i flagę, a jego PKB zostanie wyliczone z PKB per capita obecnego właściciela regionu i ludności regionu. Zacznie bez armii i środków, jako nasz sojusznik, w wojnie z obecnym właścicielem regionu.`
                                :`Region ${region} wraca do państwa ${target.name} razem z miastami i bazami (bazy przejdą puste). Nasze wojska okupacyjne wrócą do baz.`));
                            api.fields.append(make('p','Decyzja jest nieodwracalna; zamiast niej możesz anektować region.','land-muted'));
                        },async()=>{await done(await send(lw().occupationUrl,{action:'restore',occupation_id:row.id,country_id:target.countryId}));});
                        item.append(restore);
                    }
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
            // 22 Nov 2026: wszystkie decyzje w jednym rzędzie akcji okna: później | nie · tak.
            const confirm=document.getElementById('military-dialog-confirm');confirm.textContent='Tak — okupuj region';
            document.getElementById('military-dialog-cancel').textContent='Zdecyduję później';
            const no=make('button','Nie — bez okupacji','military-dialog-extra land-occupation-no');no.type='button';
            no.onclick=async()=>{no.disabled=true;try{await done(await send(lw().occupationUrl,{action:'decide',occupation_id:row.id,occupy:false}));}catch(error){document.getElementById('military-dialog-error').textContent=error.message;}finally{no.disabled=false;}};
            const group=make('div',null,'military-dialog-extra military-dialog-decision');confirm.replaceWith(group);group.append(no,confirm);
        },async()=>{await done(await send(lw().occupationUrl,{action:'decide',occupation_id:row.id,occupy:true}));});
    }

    window.GameLandWar={
        init(context){api=context;cfg=context.config;armies=lw().armies||[];occupations=lw().occupations||[];layer=L.layerGroup().addTo(api.map);draw();renderOccupations();askPending();},
        update(state){if(!api)return;armies=state.armies||armies;occupations=state.occupations||occupations;draw();drawOccupiedRegions();renderOccupations();askPending();},
        setRegions(regions,coordinates){regionGeometry=regions;toLatLng=coordinates;drawOccupiedRegions();},
        bindCity,cityActions,baseActions,regionOccupied,regionUnderOccupation,baseTooltip,baseSymbol,regionTooltip,warActions,tick,
    };
})();
