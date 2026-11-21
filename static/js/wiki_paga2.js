/* PAGA2 — zakładki panelu: profil państwa (mapa), konfiguracja, historia decyzji, stan państwa (12 Nov 2026). */
(() => {
  'use strict';
  const node=document.getElementById('paga-config');if(!node)return;
  const config=JSON.parse(node.textContent),cfg=config.paga2;if(!cfg)return;
  const catalog=cfg.catalog;
  const $=id=>document.getElementById(id);
  const make=(tag,text,className)=>{const item=document.createElement(tag);if(text!==undefined&&text!==null)item.textContent=text;if(className)item.className=className;return item;};
  const idUrl=(url,id)=>url.replace(/\/0$/,`/${id}`);
  const number=new Intl.NumberFormat('pl-PL',{maximumFractionDigits:2});
  const mld=value=>value===null||value===undefined?'—':number.format(Number(value)/1e9)+' MLD';
  const date=value=>value?new Intl.DateTimeFormat('pl-PL',{timeZone:'UTC',dateStyle:'short',timeStyle:'short'}).format(new Date(value)):'—';
  const flag=name=>cfg.flagsUrl+(name||'').replaceAll(' ','_')+'.jpg';
  async function request(url,options={}){
    const response=await fetch(url,{...options,credentials:'same-origin',cache:'no-store',headers:{'X-PAGA-Access':config.access,'X-CSRF-Token':config.csrf,...options.headers}});
    const data=await response.json().catch(()=>null);
    if(!response.ok)throw Error(data?.error||(response.status===403?'Dostęp wygasł. Odśwież stronę PAGA.':'Nie udało się odczytać lub zapisać danych PAGA2.'));
    return data;
  }
  const post=(url,body)=>request(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  function pre(value){return make('pre',JSON.stringify(value,null,2));}
  function table(headers,rows){
    const box=make('div',null,'paga-monitor-table'),t=make('table'),head=make('tr');
    for(const h of headers)head.append(make('th',h));
    const thead=make('thead');thead.append(head);const body=make('tbody');
    for(const row of rows){const tr=make('tr');for(const cell of row){const td=make('td');td.append(cell instanceof Node?cell:document.createTextNode(cell??'—'));tr.append(td);}body.append(tr);}
    t.append(thead,body);box.append(t);return box;
  }

  // ---------------- dane państw (mapa i listy) ----------------
  let countries=[],geojson=null;
  const statusOf=item=>item.status==='human'?'human':item.status==='none'?'none':item.migrated?'migrated':item.status;
  const COLORS={active:'#2f8f4e',profile:'#3d6fb6',migrated:'#e0a526',human:'#8b95a3',none:'#e4e9f0'};
  async function loadCountries(){countries=(await request(cfg.countriesUrl)).countries;return countries;}
  async function loadGeojson(){if(!geojson)geojson=await fetch(cfg.mapUrl,{credentials:'same-origin'}).then(r=>{if(!r.ok)throw Error();return r.json();});return geojson;}
  const byId=id=>countries.find(item=>item.id===Number(id));

  // ---------------- zakładki ----------------
  const loaders={},loaded=new Set();
  const tabs=[...document.querySelectorAll('[data-main-tab]')];
  function show(name,focus){
    for(const tab of tabs){const active=tab.dataset.mainTab===name;tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;document.querySelector(`[data-main-panel="${tab.dataset.mainTab}"]`).hidden=!active;}
    if(focus)tabs.find(tab=>tab.dataset.mainTab===name)?.focus();
    try{sessionStorage.setItem('paga-main-tab',name);}catch{}
    if(loaders[name]&&!loaded.has(name)){loaded.add(name);loaders[name]().catch(()=>{});}
    window.dispatchEvent(new Event('paga2:tab-'+name));
  }
  for(const tab of tabs){
    tab.addEventListener('click',()=>show(tab.dataset.mainTab));
    tab.addEventListener('keydown',event=>{const index=tabs.indexOf(tab);let next=null;
      if(event.key==='ArrowRight')next=tabs[(index+1)%tabs.length];if(event.key==='ArrowLeft')next=tabs[(index-1+tabs.length)%tabs.length];
      if(event.key==='Home')next=tabs[0];if(event.key==='End')next=tabs[tabs.length-1];
      if(next){event.preventDefault();show(next.dataset.mainTab,true);}});
  }

  // ---------------- zakładka PAGA2: profil ----------------
  const profileForm=$('paga2-profile'),profileStatus=$('paga2-profile-status'),profileError=$('paga2-profile-error');
  let profileMap=null,profileLayer=null,current=null,busy=false;
  function paintProfileMap(){
    if(!profileLayer)return;
    profileLayer.setStyle(feature=>{const item=byId(feature.properties?.panstwo_id);const selected=current&&item&&item.id===current.id;
      return {fillColor:COLORS[item?statusOf(item):'none'],fillOpacity:.85,color:selected?'#b52828':'#5b6b80',weight:selected?3:.8};});
  }
  function renderList(){
    const select=$('paga2-country'),query=$('paga2-search').value.trim().toLowerCase(),chosen=select.value;
    select.replaceChildren();
    const labels={active:'autonomia',profile:'profil',migrated:'do przeglądu',human:'gracz',none:'brak profilu'};
    for(const item of countries.filter(item=>!query||item.name.toLowerCase().includes(query)))select.append(new Option(`${item.name} — ${labels[statusOf(item)]}`,item.id));
    select.value=chosen;
  }
  async function initProfile(){
    await loadCountries();renderList();
    if(!window.L){$('paga2-map-status').textContent='Nie udało się załadować mapy. Wybierz państwo z listy.';return;}
    profileMap=L.map('paga2-map',{crs:L.CRS.Simple,minZoom:-10,maxZoom:8,zoomSnap:.25,attributionControl:false});profileMap.setView([0,0],0);
    try{
      const data=await loadGeojson();
      profileLayer=L.geoJSON(data,{coordsToLatLng:c=>L.latLng(c[1],c[0]),
        onEachFeature:(feature,polygon)=>{const item=byId(feature.properties?.panstwo_id);if(item)polygon.bindTooltip(item.name,{sticky:true});polygon.on('click',()=>{if(item)selectCountry(item.id);});}}).addTo(profileMap);
      paintProfileMap();const bounds=profileLayer.getBounds();if(bounds.isValid())profileMap.fitBounds(bounds,{padding:[10,10],animate:false});
    }catch{$('paga2-map-status').textContent='Nie udało się pobrać mapy. Wybierz państwo z listy.';}
    new ResizeObserver(()=>profileMap.invalidateSize()).observe($('paga2-map'));
  }
  loaders.profile=initProfile;
  $('paga2-search').addEventListener('input',renderList);
  $('paga2-country').addEventListener('change',event=>{if(event.target.value)selectCountry(event.target.value);});

  function renderCategories(selected){
    const box=$('paga2-categories');box.replaceChildren();
    for(const [key,item] of Object.entries(catalog.categories)){
      const label=make('label',null,'paga2-category'),input=make('input');input.type='checkbox';input.value=key;input.checked=selected.includes(key);
      const text=make('span');text.append(make('strong',item.label),make('small',item.description));
      if(item.future?.length)text.append(make('small','Jeszcze niedostępne w grze: '+item.future.join('; ')+'.','paga2-future'));
      input.addEventListener('change',limitCategories);label.append(input,text);box.append(label);
    }
    limitCategories();
  }
  function limitCategories(){const inputs=[...$('paga2-categories').querySelectorAll('input')],count=inputs.filter(i=>i.checked).length;for(const input of inputs)input.disabled=busy||(!input.checked&&count>=catalog.maxCategories);}
  function renderPriorities(chosen){
    const list=$('paga2-priority-chosen'),available=$('paga2-priority-available');list.replaceChildren();available.replaceChildren();
    chosen.forEach((key,index)=>{
      const item=make('li',null,'paga2-priority');item.dataset.key=key;item.append(make('span',String(index+1),'paga-rank'),make('span',catalog.priorities[key]));
      const controls=make('div',null,'paga-interest-controls');
      for(const [text,label,action] of [['↑','Przesuń w górę',-1],['↓','Przesuń w dół',1],['✕','Usuń',0]]){
        const button=make('button',text);button.type='button';button.setAttribute('aria-label',`${label}: ${catalog.priorities[key]}`);
        button.disabled=busy||(action===-1&&index===0)||(action===1&&index===chosen.length-1);
        button.onclick=()=>{const next=[...chosen];if(action===0)next.splice(index,1);else{next.splice(index,1);next.splice(index+action,0,key);}renderPriorities(next);(list.querySelector(`[data-key="${key}"] button[aria-label^="${label}"]`)||list).focus?.();};
        controls.append(button);
      }
      item.append(controls);list.append(item);
    });
    for(const [key,label] of Object.entries(catalog.priorities)){
      if(chosen.includes(key))continue;
      const item=make('li'),button=make('button','+ '+label);button.type='button';button.disabled=busy;button.onclick=()=>renderPriorities([...chosen,key]);item.append(button);available.append(item);
    }
    if(!chosen.length)list.append(make('li','Brak wybranych priorytetów — dodaj co najmniej jeden.','paga-note'));
  }
  const chosenPriorities=()=>[...$('paga2-priority-chosen').querySelectorAll('li[data-key]')].map(item=>item.dataset.key);
  function renderTraits(values){
    const box=$('paga2-traits');box.replaceChildren();
    for(const [key,label] of Object.entries(catalog.traits)){
      const wrap=make('div',null,'paga-trait'),name=make('label',label);name.htmlFor='paga2-trait-'+key;
      const controls=make('div',null,'paga-trait-controls'),range=make('input'),input=make('input');
      range.type='range';range.min=0;range.max=100;range.step=1;range.value=values[key];range.setAttribute('aria-label',label+' — suwak');
      input.type='number';input.min=0;input.max=100;input.step=1;input.value=values[key];input.id='paga2-trait-'+key;input.dataset.trait=key;input.inputMode='numeric';
      range.addEventListener('input',()=>{input.value=range.value;});
      input.addEventListener('input',()=>{if(input.value!==''&&input.validity.valid)range.value=input.value;});
      controls.append(range,input);wrap.append(name,controls);box.append(wrap);
    }
  }
  function renderHistory(history){
    const box=$('paga2-history');box.replaceChildren();
    if(!history.length){box.append(make('p','Brak zapisanych wersji.'));return;}
    for(const row of history){const item=make('details',null,'paga-analysis');item.append(make('summary',`Wersja ${row.revision} · ${date(row.at)} · ${row.actor}`),pre(row.configuration));box.append(item);}
  }
  function applyProfile(data){
    current={...data.country,profile:data.profile};
    $('paga2-full-name').textContent=data.country.fullName;$('paga2-name').textContent=data.country.name+(data.country.human?' — państwo gracza ludzkiego':'');
    const image=$('paga2-flag');image.src=data.country.flag||flag(data.country.name);image.alt='Flaga państwa '+data.country.name;
    const p=data.profile;
    $('paga2-version').textContent=p.revision?`Wersja profilu: ${p.revision} · zapisano ${date(p.updatedAt)} · ${p.actor}`:'Państwo nie ma jeszcze profilu PAGA2.';
    $('paga2-migrated').hidden=p.source!=='migrated';
    $('paga2-autonomy').value=String(p.autonomyEnabled);$('paga2-autonomy').disabled=busy||(data.country.human&&!p.autonomyEnabled);
    renderCategories(p.categories);renderPriorities(p.priorities);renderTraits(p.traits);renderHistory(data.history||[]);
    profileForm.hidden=false;paintProfileMap();
  }
  async function selectCountry(id){
    profileError.textContent='';profileStatus.textContent='Wczytywanie profilu…';
    try{const data=await request(idUrl(cfg.countryUrl,id));$('paga2-country').value=String(id);applyProfile(data);profileStatus.textContent='';}
    catch(exc){profileStatus.textContent='';profileError.textContent=exc.message;}
  }
  $('paga2-reload').addEventListener('click',()=>{if(current)selectCountry(current.id);});
  profileForm.addEventListener('submit',async event=>{
    event.preventDefault();if(busy||!current)return;
    const traits={};
    for(const input of $('paga2-traits').querySelectorAll('input[data-trait]')){if(input.value===''||!input.validity.valid){input.reportValidity();return;}traits[input.dataset.trait]=Number(input.value);}
    const categories=[...$('paga2-categories').querySelectorAll('input:checked')].map(i=>i.value),priorities=chosenPriorities();
    if(!categories.length){profileError.textContent='Wybierz co najmniej jeden ogólny charakter państwa.';return;}
    if(!priorities.length){profileError.textContent='Dodaj co najmniej jeden priorytet strategiczny.';return;}
    busy=true;profileError.textContent='';profileStatus.textContent='Zapisywanie…';$('paga2-save').disabled=true;
    try{
      const data=await post(idUrl(cfg.countryUrl,current.id),{revision:current.profile.revision,categories,priorities,traits,autonomyEnabled:$('paga2-autonomy').value==='true'});
      busy=false;applyProfile({country:current,profile:data.profile,history:data.history});profileStatus.textContent='Profil zapisany.';
      await loadCountries();renderList();paintProfileMap();
    }catch(exc){profileStatus.textContent='';profileError.textContent=exc.message;}
    finally{busy=false;$('paga2-save').disabled=false;limitCategories();}
  });

  // ---------------- zakładka Konfiguracja PAGA2 ----------------
  let control=null,controlEdited=false;
  function renderControl(data){
    control=data;
    if(!controlEdited){$('paga2-enabled').checked=data.enabled;$('paga2-interval').value=data.intervalMinutes;$('paga2-interval').min=data.intervalRange[0];$('paga2-interval').max=data.intervalRange[1];}
    $('paga2-control-status').textContent=`PAGA2 ${data.enabled?'WŁĄCZONE':'WYŁĄCZONE'} · państwa z autonomią: ${data.autonomousCountries} · tempo zegara ×${data.clockSpeed} → cykl co ${number.format(data.effectiveIntervalMinutes)} min (interwał dotyczy tempa ×${data.baseSpeed}) · ostatni cykl: ${date(data.lastCycleAt)} · zmiana: ${date(data.updatedAt)} (${data.actor}) · wersja ${data.revision}`;
    const r=data.randomizer,stats=$('paga2-random-stats');stats.replaceChildren();
    for(const [value,label] of [[r.total,'wywołań łącznie'],[r.last24h,'w ostatnich 24 h'],[r.last7d,'w ostatnich 7 dniach']]){const box=make('div',null,'paga-stat');box.append(make('strong',number.format(value)),make('span',label));stats.append(box);}
    const body=$('paga2-random-countries');body.replaceChildren();
    for(const row of r.perCountry){const tr=make('tr');tr.append(make('td',row.country||('#'+row.countryId)),make('td',number.format(row.calls)));body.append(tr);}
    if(!r.perCountry.length){const tr=make('tr'),td=make('td','Randomizer nie był jeszcze wywoływany.');td.colSpan=2;tr.append(td);body.append(tr);}
    const recent=$('paga2-random-recent');recent.replaceChildren();
    for(const draw of r.recent){const item=make('details',null,'paga-analysis');item.append(make('summary',`${date(draw.at)} · ${draw.country||'#'+draw.countryId} · ${draw.reason} → ${draw.chosen}`),pre(draw.candidates));recent.append(item);}
  }
  async function loadControl(){try{renderControl((await request(cfg.controlUrl)).control);$('paga2-control-error').textContent='';}catch(exc){$('paga2-control-error').textContent=exc.message;}}
  loaders.config=loadControl;
  window.addEventListener('paga2:tab-config',()=>{if(loaded.has('config'))loadControl();});
  $('paga2-control').addEventListener('input',()=>{controlEdited=true;});
  $('paga2-control').addEventListener('submit',async event=>{
    event.preventDefault();if(!control)return;
    const enabled=$('paga2-enabled').checked,interval=Number($('paga2-interval').value);
    if(enabled&&!control.enabled&&!window.confirm('Włączyć automatyczne zarządzanie państwami przez PAGA2? Algorytm zacznie podejmować decyzje w imieniu państw z włączoną autonomią.'))return;
    if(!enabled&&control.enabled&&!window.confirm('Wyłączyć PAGA2 dla wszystkich państw?'))return;
    const button=event.submitter;button.disabled=true;$('paga2-control-error').textContent='';
    try{controlEdited=false;renderControl((await post(cfg.controlUrl,{enabled,intervalMinutes:interval,revision:control.revision})).control);}
    catch(exc){$('paga2-control-error').textContent=exc.message;}
    finally{button.disabled=false;}
  });

  // ---------------- zakładka Historia decyzji ----------------
  let historyPage=1,historyMeta=null;
  function fillSelect(select,entries,empty){const chosen=select.value;select.replaceChildren(new Option(empty,''));for(const [value,label] of entries)select.append(new Option(label,value));select.value=chosen;}
  function optionsView(options){
    if(!Array.isArray(options)||!options.length)return make('p','Brak zapisanych opcji.');
    if(options.every(o=>o&&typeof o==='object'&&('action' in o||'key' in o))){
      const rows=options.map(o=>{const factors=make('details');factors.append(make('summary','czynniki'),pre(o.factors||{}));
        return [o.label||o.action||o.key,o.score===undefined?'—':number.format(o.score),o.feasible===true?'tak':o.feasible===false?'nie':'—',o.blocked||(o.chosen?'wybrana':''),factors];});
      return table(['Opcja','Punkty','Wykonalna','Uwagi','Czynniki'],rows);
    }
    return pre(options);
  }
  async function decisionDetail(item,id){
    const body=make('div',null,'paga-decision-body');body.append(make('p','Wczytywanie…'));item.append(body);
    try{
      const d=(await request(idUrl(cfg.decisionUrl,id))).decision;body.replaceChildren();
      const dl=make('dl');for(const [k,v] of [['Tryb',historyMeta?.modes?.[d.mode]||d.mode],['Wyzwalacz',d.trigger],['Obszar',historyMeta?.domains?.[d.domain]||d.domain],['Działanie',d.action],['Cel',d.target||d.targetId||'—'],['Punkty',d.score??'—'],['Losowanie',d.randomized?'tak — randomizer':'nie'],['Data Entendy',date(d.gameAt)],['Data rzeczywista',date(d.createdAt)]]){dl.append(make('dt',k),make('dd',String(v)));}
      const options=make('section');options.append(make('h3','Rozważone opcje i punktacja'),optionsView(d.options));
      const inputs=make('section');inputs.append(make('h3','Dane wejściowe decyzji'),pre(d.inputs));
      const result=make('section');result.append(make('h3','Wynik'),d.error?make('p',d.error,'paga-problem'):pre(d.result));
      body.append(dl,options);
      if(d.draws?.length){const draws=make('section');draws.append(make('h3','Losowania randomizera'),pre(d.draws));body.append(draws);}
      body.append(inputs,result);
    }catch(exc){body.replaceChildren(make('p',exc.message,'paga-problem'));}
  }
  // 14 Nov 2026: kontenerki ze statystykami zdarzeń PAGA2 (zgodne z filtrami państwa, obszaru i trybu).
  function renderHistoryStats(data){
    const st=data.stats;if(!st)return;
    const share=value=>st.total?` (${number.format(Math.round(value*1000/st.total)/10)}%)`:'';
    const box=$('paga2-history-stats');box.replaceChildren();
    for(const [value,label,status] of [[st.total,'decyzji łącznie'],[st.byStatus.EXECUTED,'wykonanych'+share(st.byStatus.EXECUTED),'EXECUTED'],
        [st.byStatus.REJECTED,'odrzuconych przez grę'+share(st.byStatus.REJECTED),'REJECTED'],[st.byStatus.PASSIVE,'bez działania'+share(st.byStatus.PASSIVE),'PASSIVE'],
        [st.byStatus.ERROR,'błędów'+share(st.byStatus.ERROR),'ERROR'],[st.last24h,'w ostatnich 24 h'],[st.randomized,'z randomizerem'],[st.countries,'państw']]){
      const item=make('div',null,'paga-stat');if(status)item.dataset.status=status;item.append(make('strong',number.format(value||0)),make('span',label));box.append(item);
    }
    const rejected=$('paga2-history-rejected');rejected.replaceChildren();
    if(!st.topRejected.length){const row=make('tr');const cell=make('td','Brak odrzuceń.');cell.colSpan=3;row.append(cell);rejected.append(row);}
    for(const item of st.topRejected){const row=make('tr');row.append(make('td',item.action),make('td',data.domains[item.domain]||item.domain),make('td',number.format(item.count)));rejected.append(row);}
    const domains=$('paga2-history-domains');domains.replaceChildren();
    for(const item of st.domains){const row=make('tr');row.append(make('td',data.domains[item.domain]||item.domain),make('td',number.format(item.count)));domains.append(row);}
  }
  async function loadHistory(){
    const params=new URLSearchParams({page:historyPage,country:$('paga2-history-country').value,domain:$('paga2-history-domain').value,status:$('paga2-history-status').value,mode:$('paga2-history-mode').value});
    try{
      const data=await request(cfg.decisionsUrl+'?'+params);historyMeta=data;
      fillSelect($('paga2-history-country'),data.countries.map(c=>[c.id,c.name]),'Wszystkie państwa');
      fillSelect($('paga2-history-domain'),Object.entries(data.domains),'Wszystkie obszary');
      fillSelect($('paga2-history-status'),Object.entries(data.statuses),'Wszystkie statusy');
      fillSelect($('paga2-history-mode'),Object.entries(data.modes),'Wszystkie tryby');
      renderHistoryStats(data);
      const list=$('paga2-history-list');list.replaceChildren();
      for(const row of data.items){
        const item=make('details',null,'paga-decision'),summary=make('summary');
        const who=make('span',null,'paga-who'),image=make('img');image.src=flag(row.country);image.alt='';image.onerror=()=>image.remove();who.append(image,make('span',row.country||'#'+row.countryId));
        const what=make('div',null,'paga-what');what.append(make('b',`${data.domains[row.domain]||row.domain}: ${row.action}${row.target?' → '+row.target:''}`),make('p',`${data.modes[row.mode]||row.mode} · ${row.trigger}${row.randomized?' · randomizer':''}`));
        const badges=make('span',null,'paga-badges'),badge=make('span',data.statuses[row.status]||row.status,'paga-badge');badge.dataset.status=row.status;badges.append(badge);if(row.score!==null)badges.append(make('span',number.format(row.score)+' pkt','paga-badge'));
        summary.append(make('span',date(row.gameAt),'paga-when'),who,what,badges);item.append(summary);
        item.addEventListener('toggle',()=>{if(item.open&&!item.dataset.loaded){item.dataset.loaded='1';decisionDetail(item,row.id);}});
        list.append(item);
      }
      $('paga2-history-info').textContent=data.items.length?'':'Brak decyzji PAGA2 dla wybranych filtrów. Decyzje pojawią się po uruchomieniu silnika decyzji.';
      $('paga2-history-page').textContent='Strona '+data.page;$('paga2-history-prev').disabled=data.page<=1;$('paga2-history-next').disabled=!data.hasMore;
    }catch(exc){$('paga2-history-info').textContent=exc.message;}
  }
  loaders.history=loadHistory;
  $('paga2-history-filter').addEventListener('submit',event=>{event.preventDefault();historyPage=1;loadHistory();});
  $('paga2-history-reset').addEventListener('click',()=>{for(const id of ['country','domain','status','mode'])$('paga2-history-'+id).value='';historyPage=1;loadHistory();});
  $('paga2-history-prev').onclick=()=>{historyPage=Math.max(1,historyPage-1);loadHistory();};$('paga2-history-next').onclick=()=>{historyPage++;loadHistory();};

  // ---------------- zakładka Stan państwa PAGA ----------------
  const ARMY={wojska_ladowe_ilosc:'Żołnierze wojsk lądowych',wojska_morskie_ilosc:'Marynarze',wojska_powietrzne_ilosc:'Lotnicy',czolgi_ilosc:'Czołgi',wozy_opancerzone_ilosc:'Wozy opancerzone',mysliwce_ilosc:'Myśliwce',drony_ilosc:'Drony',wyrzutnie_rakiet_ilosc:'Wyrzutnie rakiet',okrety_wojenne_ilosc:'Okręty wojenne',okrety_podwodne_ilosc:'Okręty podwodne',lotniskowce_ilosc:'Lotniskowce',bron_atomowa_ilosc:'Broń atomowa',rakiety_krotkiego_zasiegu:'Rakiety krótkiego zasięgu',rakiety_sredniego_zasiegu:'Rakiety średniego zasięgu',rakiety_dalekiego_zasiegu:'Rakiety dalekiego zasięgu',wyszkolenie_ladowe:'Wyszkolenie lądowe',wyszkolenie_morskie:'Wyszkolenie morskie',wyszkolenie_powietrzne:'Wyszkolenie powietrzne',liczba_baz_ladowych:'Bazy lądowe (WIKI)',liczba_baz_morskich:'Bazy morskie (WIKI)',liczba_baz_powietrznych:'Bazy powietrzne (WIKI)'};
  const KIND_COLORS={base_land:'#5b7f3a',base_air:'#2f6db3',base_naval:'#1d8a99',base_nuclear:'#8a1c1c',mine:'#8a5a2b',factory:'#6b4fa3',power:'#d08a00',radar:'#c2185b'};
  let stateMap=null,stateLayer=null,stateCountry=null;
  async function initState(){
    if(!countries.length)await loadCountries();
    const select=$('paga2-state-country');
    fillSelect(select,countries.filter(c=>c.status==='active'||c.status==='profile').map(c=>[c.id,c.name+(c.status==='active'?' — autonomia':'')]),'Wybierz państwo');
  }
  loaders.state=initState;
  function renderStateMap(state){
    if(!window.L)return;
    if(!stateMap){stateMap=L.map('paga2-state-map',{crs:L.CRS.Simple,minZoom:-10,maxZoom:8,zoomSnap:.25,attributionControl:false});stateMap.setView([0,0],0);new ResizeObserver(()=>stateMap.invalidateSize()).observe($('paga2-state-map'));}
    if(stateLayer)stateLayer.remove();
    stateLayer=L.layerGroup().addTo(stateMap);
    loadGeojson().then(data=>{
      const own=L.geoJSON(data,{coordsToLatLng:c=>L.latLng(c[1],c[0]),filter:f=>f.properties?.panstwo_id===state.country.id,style:{fillColor:'#3d6fb6',fillOpacity:.25,color:'#203c60',weight:2}}).addTo(stateLayer);
      const neighbors=L.geoJSON(data,{coordsToLatLng:c=>L.latLng(c[1],c[0]),filter:f=>f.properties?.panstwo_id!==state.country.id,style:{fillColor:'#e4e9f0',fillOpacity:.5,color:'#9aa6b5',weight:.6},interactive:false});
      neighbors.addTo(stateLayer);own.bringToFront();
      for(const item of state.objects){
        if(item.x===null||item.y===null)continue;
        L.circleMarker([item.y,item.x],{radius:6,color:'#fff',weight:1.5,fillColor:KIND_COLORS[item.kind]||'#333',fillOpacity:1})
          .bindTooltip(`${state.counts[item.kind]?.label||item.kind}${item.name?': '+item.name:''}${item.resource?' ('+item.resource+')':''}${item.level?' · poziom '+item.level:''}${item.health!==null&&item.health!==undefined?' · życie '+item.health:''}`).addTo(stateLayer);
      }
      const bounds=own.getBounds();if(bounds.isValid())stateMap.fitBounds(bounds,{padding:[20,20],animate:false});
      setTimeout(()=>stateMap.invalidateSize(),50);
    }).catch(()=>{$('paga2-state-status').textContent='Nie udało się pobrać mapy.';});
    const legend=$('paga2-state-legend');legend.replaceChildren();
    for(const [kind,color] of Object.entries(KIND_COLORS)){if(!state.counts[kind]?.count)continue;const li=make('li');const sw=make('span',null,'paga2-swatch');sw.style.background=color;li.append(sw,document.createTextNode(state.counts[kind].label));legend.append(li);}
  }
  function renderState(state){
    $('paga2-state').hidden=false;
    $('paga2-state-name').textContent=state.country.fullName;const image=$('paga2-state-flag');image.src=flag(state.country.name);image.alt='Flaga państwa '+state.country.name;
    const p=state.profile;
    $('paga2-state-profile').textContent=`Autonomia: ${p.autonomyEnabled?'włączona':'wyłączona'} · charakter: ${p.categories.map(c=>catalog.categories[c]?.label||c).join(', ')||'—'} · priorytety: ${p.priorities.map(k=>catalog.priorities[k]||k).join(' › ')||'—'}`;
    const f=state.finance,fin=$('paga2-state-finance');fin.replaceChildren();
    const dl=make('dl',null,'paga2-dl');for(const [k,v] of [['Rezerwa skarbu',mld(f.reserve)],...(f.budget?[['Okres budżetu',`${f.budget.year}/${f.budget.period}`],['Dochody podatkowe',mld(f.budget.tax)],['Budżet łącznie',mld(f.budget.total)],['Wydatki',mld(f.budget.expenditure)],['Rezerwa na koniec',mld(f.budget.closing)],['Tryb zatwierdzenia',f.budget.mode]]:[['Budżet','brak zatwierdzonego budżetu']])])dl.append(make('dt',k),make('dd',v));fin.append(dl);
    const budget=$('paga2-state-budget');budget.replaceChildren();
    if(f.budget?.allocations?.length){const remaining=Object.fromEntries((f.remaining||[]).map(r=>[r.code,r.remaining]));budget.append(table(['Sektor','Udział','Kwota','Pozostało'],f.budget.allocations.map(a=>[a.label,a.share===null?'—':number.format(a.share)+'%',mld(a.amount),mld(remaining[a.code])])));}
    else budget.append(make('p','Brak ustalonego budżetu.'));
    $('paga2-state-objects').replaceChildren(table(['Rodzaj','Liczba'],Object.values(state.counts).map(c=>[c.label,number.format(c.count)])));
    const army=Object.entries(state.army).filter(([k])=>ARMY[k]);$('paga2-state-army').replaceChildren(army.length?table(['Siły','Stan'],army.map(([k,v])=>[ARMY[k],v===null?'—':number.format(v)])):make('p','Brak danych o siłach zbrojnych.'));
    const tech=$('paga2-state-tech');tech.replaceChildren(make('p',`Niewykorzystane punkty rozwoju: ${number.format(state.researchPoints)}`));
    tech.append(state.technologies.length?table(['Technologia','Postęp','Stan'],state.technologies.map(t=>[t.label,`${number.format(t.invested)} / ${number.format(t.cost)}`,t.developed?'rozwinięta':'w toku'])):make('p','Brak rozwiniętych technologii.'));
    // 21 Nov 2026: plany wojenne PAGA2 — cel, etap, gotowość w pięciu obszarach, rozpoznanie, braki i historia
    const warBox=$('paga2-state-war-plans');
    if(warBox){warBox.replaceChildren();
      const pct=v=>`${Math.round(100*Number(v||0))}%`;
      for(const plan of state.warPlans||[]){
        const item=make('details',null,'paga-decision'),summary=make('summary');
        const what=make('div',null,'paga-what');
        what.append(make('b',`Plan #${plan.id}: ${plan.kind==='ALLY_SUPPORT'?'wsparcie sojusznika '+(plan.ally||'#'+plan.allyId)+' — ':''}przeciwnik ${plan.enemy||'#'+plan.enemyId}`),
                    make('p',`${plan.goal?.label||'cel'} · gotowość ${pct(plan.readiness)} · operacje: ${plan.operations}`));
        const badges=make('span',null,'paga-badges'),badge=make('span',plan.stageLabel,'paga-badge');
        badge.dataset.status=plan.stage==='COMPLETED'?'EXECUTED':plan.stage==='ABANDONED'?'ERROR':'';badges.append(badge);
        summary.append(make('span',date(plan.createdAt),'paga-when'),make('span',plan.stage,'paga-who'),what,badges);item.append(summary);
        const body=make('div',null,'paga-decision-body');
        body.append(make('p',`Przyczyna: ${plan.reason}`));
        if(plan.endReason)body.append(make('p',`Powód zakończenia: ${plan.endReason}`));
        body.append(table(['Obszar gotowości','Posiadane','Wymagane','Pokrycie'],Object.entries(plan.areas||{}).map(([k,a])=>[plan.areaLabels?.[k]||k,number.format(Number(a.have||0)),number.format(Number(a.need||0)),pct(a.ratio)])));
        if((plan.shortfalls||[]).length)body.append(make('p','Braki blokujące wojnę: '+plan.shortfalls.join('; ')));
        body.append(make('p',`Rozpoznanie: ${(plan.areas?.intel?.ratio||0)>=1?'aktualne':'brak aktualnego'} · próby wywiadu: ${plan.intelAttempts} · cykle bez operacji: ${plan.idleCycles}`));
        if((plan.targets||[]).length)body.append(make('p','Cele militarne: '+plan.targets.map(t=>t.label).join(', ')));
        for(const n of plan.notes||[])body.append(make('p',n,'paga-note'));
        if((plan.history||[]).length)body.append(table(['Czas Entendy','Zdarzenie'],plan.history.slice().reverse().map(h=>[date(h.at),h.text])));
        item.append(body);warBox.append(item);
      }
      if(!(state.warPlans||[]).length)warBox.append(make('p','Państwo nie ma planów wojennych.'));
    }
    // 21 Nov 2026: obiekty miejskie w miastach państwa (budynki postawione przez PAGA2)
    const cityBox=$('paga2-state-cities');
    if(cityBox){cityBox.replaceChildren();
      for(const city of state.cities||[]){
        const item=make('details',null,'paga-analysis'),built=city.buildings.filter(b=>b.completed).length;
        item.append(make('summary',`${city.name}${city.capital?' (stolica)':''} · ludność ${number.format(city.population)} · obiekty: ${city.buildings.length}${built<city.buildings.length?` (w budowie: ${city.buildings.length-built})`:''}`));
        item.append(table(['Obiekt','Kratka','Stan','Utrzymanie / rok'],city.buildings.map(b=>[b.label,`${Math.floor(b.cell/8)+1}–${b.cell%8+1}`,b.underfunded?'niedofinansowany':b.completed?'działa':`budowa ${b.progress}% (do ${date(b.readyAt)})`,number.format(Number(b.maintenance)/1e6)+' mln ROI'])));
        cityBox.append(item);
      }
      if(!(state.cities||[]).length)cityBox.append(make('p','Państwo nie postawiło jeszcze obiektów miejskich.'));
    }
    const stocks=Object.entries(state.stocks);$('paga2-state-stocks').replaceChildren(stocks.length?table(['Surowiec','Ilość'],stocks.map(([k,v])=>[k,number.format(v)])):make('p','Magazyn jest pusty.'));
    $('paga2-state-relations').replaceChildren(state.relations.length?table(['Państwo','Relacja','Stan'],state.relations.map(r=>[r.country||'#'+r.countryId,r.relation,r.state])):make('p','Brak zapisanych relacji.'));
    const plans=$('paga2-state-plans');plans.replaceChildren();
    const PLAN_STATUS={ACTIVE:'w realizacji',DONE:'osiągnięty',IMPOSSIBLE:'niemożliwy',ABANDONED:'porzucony'};
    const STEP_STATUS={done:'✓ wykonany',ready:'→ gotowy do wykonania',blocked:'… oczekuje',building:'⌛ w budowie',external:'⇄ zakup w handlu'};
    for(const plan of state.plans||[]){
      const item=make('details',null,'paga-decision'),summary=make('summary');
      const what=make('div',null,'paga-what');what.append(make('b',plan.label),make('p',`${plan.priority||'—'} · ${plan.reason||''}`));
      const badges=make('span',null,'paga-badges'),badge=make('span',PLAN_STATUS[plan.status]||plan.status,'paga-badge');badge.dataset.status=plan.status==='DONE'?'EXECUTED':plan.status==='ACTIVE'?'':'ERROR';badges.append(badge);
      summary.append(make('span',date(plan.updatedAt),'paga-when'),make('span',`Plan #${plan.id}`,'paga-who'),what,badges);item.append(summary);
      const body=make('div',null,'paga-decision-body');
      body.append(table(['Etap','Stan','Koszt'],(plan.steps||[]).map(s=>[s.label+(s.reason?` (${s.reason})`:''),STEP_STATUS[s.status]||s.status,s.cost?mld(s.cost):'—'])));
      item.append(body);plans.append(item);
    }
    if(!(state.plans||[]).length)plans.append(make('p','Państwo nie ma jeszcze planów wieloetapowych.'));
    const messages=$('paga2-state-messages');messages.replaceChildren();
    for(const m of state.messages){const item=make('details',null,'paga-analysis');item.append(make('summary',`${date(m.at)} · ${m.outgoing?'do: '+m.to:'od: '+m.from}${m.read?'':' · nieprzeczytana'}`),make('p',m.content));messages.append(item);}
    if(!state.messages.length)messages.append(make('p','Brak wiadomości prywatnych.'));
    renderStateMap(state);
  }
  async function loadState(){
    const id=$('paga2-state-country').value;$('paga2-state-refresh').disabled=!id;if(!id){$('paga2-state').hidden=true;return;}
    $('paga2-state-error').textContent='';$('paga2-state-status').textContent='Wczytywanie stanu państwa…';
    try{stateCountry=id;const data=await request(idUrl(cfg.stateUrl,id));if(stateCountry!==id)return;renderState(data.state);$('paga2-state-status').textContent='';}
    catch(exc){$('paga2-state-status').textContent='';$('paga2-state-error').textContent=exc.message;}
  }
  $('paga2-state-country').addEventListener('change',loadState);$('paga2-state-refresh').addEventListener('click',loadState);

  // start: ostatnio otwarta zakładka
  let initial='paga';try{initial=sessionStorage.getItem('paga-main-tab')||'paga';}catch{}
  if(!tabs.some(tab=>tab.dataset.mainTab===initial))initial='paga';
  show(initial);
})();
