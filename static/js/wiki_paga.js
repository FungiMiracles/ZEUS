(() => {
  'use strict';
  const node=document.getElementById('paga-config');if(!node)return;
  const config=JSON.parse(node.textContent),form=document.getElementById('paga-form'),continent=document.getElementById('paga-continent'),search=document.getElementById('paga-search'),country=document.getElementById('paga-country'),list=document.getElementById('paga-interests'),error=document.getElementById('paga-error'),status=document.getElementById('paga-status');
  let revision=0,countryId=null,busy=false,listRequest=0,countryRequest=0,dragged=null,timer;
  const make=(tag,text)=>{const item=document.createElement(tag);if(text!==undefined)item.textContent=text;return item;};
  const url=id=>config.countryUrl.replace(/\/0$/,`/${id}`);
  async function request(url,options={}){
    const response=await fetch(url,{...options,credentials:'same-origin',cache:'no-store',headers:{'X-PAGA-Access':config.access,'X-CSRF-Token':config.csrf,...options.headers}});
    const data=await response.json().catch(()=>null);
    if(!response.ok)throw Error(data?.error||(response.status===403?'Dostęp wygasł. Odśwież stronę PAGA.':'Nie udało się odczytać lub zapisać konfiguracji.'));
    return data;
  }
  const aiToggle=document.getElementById('paga-ai-toggle');
  if(aiToggle&&config.aiUrl){
    let ai=null,changing=false;
    const aiState=document.getElementById('paga-ai-state'),aiError=document.getElementById('paga-ai-error');
    function seconds(ms){return ms==null?'—':(ms/1000).toFixed(1)+' s';}
    function renderAiMetrics(m){
      const box=document.getElementById('paga-ai-metrics');if(!box)return;
      if(!m){box.textContent='Metryki niedostępne (wymagana migracja).';return;}
      const ok=(m.calls||{}).OK||{};
      box.textContent=`Zadania zakończone: ${m.completed} · nieudane: ${m.failed} · timeouty: ${m.timeouts} · ponowienia: ${m.retries} · `+
        `średnio ${m.avg_model_calls_per_task??'—'} wywołań/zadanie · średni czas zadania ${seconds(m.avg_task_ms)} · `+
        `wywołanie: ${seconds(ok.avg_ms)}, prompt ${ok.avg_prompt_tokens??'—'} tok. (${seconds(ok.avg_prompt_ms)}), odpowiedź ${ok.avg_generated_tokens??'—'} tok. (${seconds(ok.avg_generation_ms)}), szczyt RAM ${ok.peak_rss_bytes?(ok.peak_rss_bytes/1073741824).toFixed(2)+' GiB':'—'}`;
    }
    function renderProviders(data){
      const box=document.getElementById('paga-ai-providers');if(!box)return;
      if(!data){box.textContent='Stan modeli niedostępny (wymagana migracja).';return;}
      const list=document.createElement('ul');
      for(const p of data.providers||[]){
        const limits=p.limits&&p.limits.rpm?` · limity: ${p.limits.rpm}/min, ${p.limits.rpd}/dobę, ${p.limits.tpm} tok./min`:'';
        const key=p.keyPresent===null?'':` · klucz API: ${p.keyPresent?'jest':'brak'}`;
        const paused=Object.entries(p.pausedModels||{}).map(([model,until])=>`${model} do ${until}`).join(', ');
        list.append(make('li',`${p.label} (${p.role}) — ${p.model} · ${p.available?'dostępny':'niedostępny: '+(p.reason||'')}${key}${limits} · wywołania 24 h: ${p.calls24h}, limity przekroczone: ${p.rateLimited24h}${paused?' · wstrzymane modele: '+paused:''}`));
      }
      box.replaceChildren(make('p',data.writesEnabled?'Operacje zmieniające stan gry: włączone (PAGA_AUTONOMOUS_WRITES_ENABLED=true).':'Operacje zmieniające stan gry: WYŁĄCZONE (PAGA_AUTONOMOUS_WRITES_ENABLED=false) — modele decydują, ZEUS niczego nie wykonuje.'),list);
    }
    let settingsEdited=false;
    function renderAiSettings(settings){
      if(!settings||settingsEdited)return;
      document.getElementById('paga-ai-review').value=settings.reviewIntervalMinutes;document.getElementById('paga-ai-calls').value=settings.maxModelCalls;
    }
    const settingsForm=document.getElementById('paga-ai-settings');
    if(settingsForm&&config.aiSettingsUrl){
      settingsForm.addEventListener('input',()=>{settingsEdited=true;});
      settingsForm.addEventListener('submit',async event=>{event.preventDefault();aiError.textContent='';
        try{await request(config.aiSettingsUrl,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reviewIntervalMinutes:Number(document.getElementById('paga-ai-review').value),maxModelCalls:Number(document.getElementById('paga-ai-calls').value)})});settingsEdited=false;await loadAi();}
        catch(exc){aiError.textContent=exc.message;}});
    }
    // Audit rows never change, so the 15 s refresh only adds new rows and drops ones that left the list.
    // Existing <details> stay untouched: an expanded record stays open and a text selection inside it survives.
    function renderAiLogs(rows){
      const logs=document.getElementById('paga-ai-logs'),wanted=new Set(rows.map(row=>String(row.id)));
      for(const node of [...logs.children])if(!wanted.has(node.dataset.logId))node.remove();
      let cursor=logs.firstElementChild;
      for(const row of rows){
        const id=String(row.id);
        if(cursor&&cursor.dataset.logId===id){cursor=cursor.nextElementSibling;continue;}
        let item=logs.querySelector(`:scope > details[data-log-id="${CSS.escape(id)}"]`);
        if(!item){item=make('details');item.dataset.logId=id;item.append(make('summary',row.gameAt+' · państwo #'+row.countryId+' · '+row.operation+' · '+row.validation),make('pre',JSON.stringify(row,null,2)));}
        logs.insertBefore(item,cursor);
      }
    }
    async function loadAi(){
      try{ai=await request(config.aiUrl);aiToggle.textContent='Modele AI (forum, wiadomości, pożyczki) — '+(ai.enabled?'WŁĄCZONE':'WYŁĄCZONE');aiToggle.setAttribute('aria-pressed',String(ai.enabled));aiToggle.disabled=false;aiState.textContent=ai.model+' · '+Object.entries(ai.jobs).map(([kind,count])=>kind+': '+count).join(' · ');renderAiLogs(ai.logs);renderAiMetrics(ai.metrics);renderProviders(ai.providers);renderAiSettings(ai.settings);}
      catch(exc){aiError.textContent=exc.message;aiToggle.disabled=true;}
    }
    aiToggle.addEventListener('click',async()=>{if(changing||!ai)return;changing=true;aiToggle.disabled=true;aiError.textContent='';try{await request(config.aiUrl,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:!ai.enabled,revision:ai.revision})});}catch(exc){aiError.textContent=exc.message;}finally{await loadAi();changing=false;}});
    loadAi();setInterval(()=>{if(!changing)loadAi();},15000);
  }
  let monitorPage=1,controlRevision=0;
  const monitor=document.getElementById('paga-monitor'),monitorStatus=document.getElementById('paga-monitor-status');
  function details(title,value){const item=make('details');item.className='paga-analysis';item.append(make('summary',title),make('pre',JSON.stringify(value,null,2)));return item;}
  async function loadMonitor(){
    const selected=document.getElementById('paga-monitor-country'),filters=new URLSearchParams({page:monitorPage,country:selected.value,from:document.getElementById('paga-monitor-from').value,to:document.getElementById('paga-monitor-to').value,kind:document.getElementById('paga-monitor-kind').value});
    try{
      const data=await request(config.monitorUrl+'?'+filters),control=data.control;controlRevision=control.revision;const kinds=document.getElementById('paga-decision-kinds');kinds.replaceChildren();for(const value of data.actionKinds||[])kinds.append(new Option(value,value));
      
      const chosen=selected.value;selected.replaceChildren(new Option('Wszystkie państwa',''));for(const item of data.countries)selected.append(new Option(item.name+(item.eligible?' — autonomia aktywna':item.human?' — gracz ludzki':''),item.id));selected.value=chosen;
      const format=value=>value?new Intl.DateTimeFormat('pl-PL',{timeZone:'UTC',dateStyle:'short',timeStyle:'short'}).format(new Date(value)):'—';
      monitorStatus.textContent=`Silnik wyłączony na stałe (zastąpiony przez PAGA2). Strona ${data.page}.`;
      const schedules=document.getElementById('paga-schedules');schedules.replaceChildren();for(const item of data.schedules){const row=make('tr');row.append(make('td',item.country||item.countryId),make('td',format(item.nextAt)),make('td',item.error||(!item.eligible?'Wstrzymano / państwo gracza':'Oczekuje')));schedules.append(row);}
      const history=document.getElementById('paga-analyses');history.replaceChildren();for(const item of data.analyses)history.append(details(`${format(item.date)} · ${item.country} · ${item.action} → ${item.target||'—'} · ${item.status} · ocena ${item.score??'—'}`,item));if(!data.analyses.length)history.append(make('p','Brak analiz dla wybranych filtrów.'));
      const memory=document.getElementById('paga-memories');memory.replaceChildren();if(data.assessments.length)memory.append(details('Oceny innych państw: zaufanie, zagrożenie i wiarygodność informacji',data.assessments));for(const item of data.memories)memory.append(details(`${format(item.date)} · ${item.kind} · ${item.public?'jawne':'wiedza własna państwa'}`,item));
      document.getElementById('paga-monitor-prev').disabled=monitorPage===1;document.getElementById('paga-monitor-next').disabled=!data.hasMore;
    }catch(exc){monitorStatus.textContent=exc.message;}
  }
  monitor.addEventListener('toggle',()=>{if(monitor.open)loadMonitor();});
  document.getElementById('paga-monitor-filter').addEventListener('submit',event=>{event.preventDefault();monitorPage=1;loadMonitor();});
  document.getElementById('paga-monitor-prev').onclick=()=>{monitorPage=Math.max(1,monitorPage-1);loadMonitor();};document.getElementById('paga-monitor-next').onclick=()=>{monitorPage++;loadMonitor();};
  // Dotychczasowy formularz cech i interesów PAGA zastąpił profil PAGA2 (zakładka PAGA2).
  if(!form)return;
  function complete(){return Object.keys(config.traits).every(key=>{const input=form.querySelector(`[data-trait-value="${key}"]`);return input.value!==''&&input.validity.valid&&Number.isInteger(Number(input.value));})&&!!list.querySelector('input:checked');}
  function validity(){document.getElementById('paga-approve').disabled=busy||!complete();document.getElementById('paga-draft').disabled=busy;}
  function sync(key,value){const range=form.querySelector(`[data-trait-range="${key}"]`),input=form.querySelector(`[data-trait-value="${key}"]`);input.value=value??'';range.value=value??0;range.dataset.unset=String(value===null||value==='');range.setAttribute('aria-valuetext',value===null||value===''?'Nie ustawiono':String(value));validity();}
  for(const key of Object.keys(config.traits)){
    const range=form.querySelector(`[data-trait-range="${key}"]`),input=form.querySelector(`[data-trait-value="${key}"]`);
    range.addEventListener('input',()=>sync(key,range.value));
    range.addEventListener('pointerdown',()=>{if(range.dataset.unset==='true')sync(key,range.value);});
    range.addEventListener('keydown',event=>{if(['Home','End','ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)&&range.dataset.unset==='true')sync(key,range.value);});
    input.addEventListener('input',()=>{if(input.value===''||input.validity.valid)sync(key,input.value);else validity();});
  }
  function ranks(){Array.from(list.children).forEach((item,index)=>{item.querySelector('.paga-rank').textContent=index+1;item.querySelector('[data-move=up]').disabled=busy||index===0;item.querySelector('[data-move=down]').disabled=busy||index===list.children.length-1;});}
  function renderInterests(interests){
    list.replaceChildren();
    for(const interest of interests){
      const item=make('li');item.className='paga-interest';item.dataset.key=interest.key;item.dataset.active=String(interest.active);item.draggable=true;
      const rank=make('span');rank.className='paga-rank';const label=make('label'),active=make('input');active.type='checkbox';active.checked=interest.active;active.setAttribute('aria-label',`Aktywuj interes: ${config.interests[interest.key]}`);label.append(active,make('span',config.interests[interest.key]));
      active.addEventListener('change',()=>{item.dataset.active=String(active.checked);validity();});
      const controls=make('div');controls.className='paga-interest-controls';
      for(const [direction,text] of [['up','↑'],['down','↓']]){const button=make('button',text);button.type='button';button.dataset.move=direction;button.setAttribute('aria-label',`${direction==='up'?'Przesuń w górę':'Przesuń w dół'}: ${config.interests[interest.key]}`);button.onclick=()=>{if(direction==='up'&&item.previousElementSibling)list.insertBefore(item,item.previousElementSibling);if(direction==='down'&&item.nextElementSibling)list.insertBefore(item.nextElementSibling,item);ranks();button.focus();};controls.append(button);}
      item.append(rank,label,controls);item.addEventListener('dragstart',event=>{if(busy){event.preventDefault();return;}dragged=item;item.classList.add('dragging');event.dataTransfer.setData('text/plain',interest.key);event.dataTransfer.effectAllowed='move';});
      item.addEventListener('dragover',event=>{if(dragged&&dragged!==item)event.preventDefault();});
      item.addEventListener('drop',event=>{event.preventDefault();if(!dragged||dragged===item)return;const lower=event.clientY>item.getBoundingClientRect().top+item.offsetHeight/2;list.insertBefore(dragged,lower?item.nextSibling:item);ranks();});
      item.addEventListener('dragend',()=>{item.classList.remove('dragging');dragged=null;});list.append(item);
    }
    ranks();validity();
  }
  function apply(state){revision=state.revision;document.getElementById("paga-autonomy").value=String(state.autonomyEnabled);document.getElementById("paga-autonomy-current").textContent="Autonomia obowiązująca: "+(state.approvedAutonomyEnabled?"Włączona":"Wyłączona")+".";renderInterests(state.interests);for(const key of Object.keys(config.traits))sync(key,state.character[key]);document.getElementById('paga-version').textContent=(state.approvedAt?'Konfiguracja obowiązująca: zatwierdzona. ':'Brak zatwierdzonej konfiguracji. ')+(state.draftUpdatedAt?'Wyświetlasz wersję roboczą.':'')+` Wersja zapisu: ${state.revision}.`;validity();}
  async function countries(){
    const generation=++listRequest;++countryRequest;countryId=null;form.hidden=true;country.disabled=true;country.replaceChildren(new Option(continent.value?'Ładowanie…':'Najpierw wybierz kontynent',''));search.disabled=!continent.value;
    if(!continent.value)return;
    try{const data=await request(config.countriesUrl+'?'+new URLSearchParams({continent:continent.value,q:search.value}));if(generation!==listRequest)return;country.replaceChildren(new Option('Wybierz państwo',''));for(const item of data.countries)country.append(new Option(item.name,item.id));country.disabled=false;if(!data.countries.length)country.options[0].textContent='Brak pasujących państw';}catch(exc){if(generation===listRequest)error.textContent=exc.message;}
  }
  continent.addEventListener('change',()=>{clearTimeout(timer);search.value='';error.textContent='';status.textContent='';countries();});
  search.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(countries,200);});
  country.addEventListener('change',async()=>{const generation=++countryRequest;countryId=null;form.hidden=true;error.textContent='';status.textContent='';if(!country.value)return;try{const data=await request(url(country.value));if(generation!==countryRequest)return;countryId=data.country.id;document.getElementById('paga-full-name').textContent=data.country.fullName;document.getElementById('paga-name').textContent=data.country.name;const flag=document.getElementById('paga-flag');flag.src=data.country.flag;flag.alt='Flaga państwa '+data.country.name;form.hidden=false;apply(data.configuration);}catch(exc){if(generation===countryRequest)error.textContent=exc.message;}});
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(busy||countryId===null)return;
    const mode=event.submitter?.value;if(!['draft','approve'].includes(mode))return;
    const character={};for(const key of Object.keys(config.traits)){const input=form.querySelector(`[data-trait-value="${key}"]`);if(!input.validity.valid){input.reportValidity();return;}character[key]=input.value===''?null:Number(input.value);}
    const interests=Array.from(list.children,item=>({key:item.dataset.key,active:item.querySelector('input').checked}));
    busy=true;error.textContent='';status.textContent='Zapisywanie…';form.querySelectorAll('input,select,button').forEach(item=>item.disabled=true);continent.disabled=country.disabled=search.disabled=true;
    try{const data=await request(url(countryId),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode,revision,character,interests,autonomyEnabled:document.getElementById("paga-autonomy").value==='true'})});apply(data.configuration);status.textContent=mode==='approve'?'Konfiguracja zatwierdzona.':'Zapisano wersję roboczą. Konfiguracja obowiązująca pozostaje bez zmian.';}catch(exc){status.textContent='';error.textContent=exc.message;}finally{busy=false;form.querySelectorAll('input,select,button').forEach(item=>item.disabled=false);continent.disabled=country.disabled=search.disabled=false;ranks();validity();}
  });
})();
