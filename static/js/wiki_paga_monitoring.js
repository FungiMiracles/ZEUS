(() => {
  'use strict';
  const PROVIDER_LABELS={gemini:'Gemini',groq:'Groq',qwen:'Qwen',zeus:'ZEUS'};
  // PAGA decision monitor (UAT): read-only views of real PAGA data; never triggers model calls.
  const node=document.getElementById('paga-config');if(!node)return;
  const config=JSON.parse(node.textContent);if(!config.monitoringUrl)return;
  const $=id=>document.getElementById(id);
  const make=(tag,text,className)=>{const item=document.createElement(tag);if(text!==undefined&&text!==null)item.textContent=String(text);if(className)item.className=className;return item;};
  const REFRESH_MS=15000;
  async function request(url){
    const response=await fetch(url,{credentials:'same-origin',cache:'no-store',headers:{'X-PAGA-Access':config.access,'X-CSRF-Token':config.csrf}});
    const data=await response.json().catch(()=>null);
    if(!response.ok)throw Error(data?.error||(response.status===403?'Dostęp wygasł. Odśwież stronę PAGA.':'Nie udało się odczytać monitoringu.'));
    return data;
  }
  const format=value=>{if(!value)return '—';const date=new Date(value);return Number.isNaN(date.getTime())?String(value):new Intl.DateTimeFormat('pl-PL',{dateStyle:'short',timeStyle:'medium'}).format(date);};
  const game=value=>value?String(value).replace('T',' ').slice(0,16):'—';
  const seconds=ms=>ms==null?'—':(ms/1000).toFixed(1)+' s';
  const json=value=>JSON.stringify(value,null,2);

  // ---- state: applied filters survive every refresh; only "Zastosuj" changes them ----
  const filterForm=$('paga-decision-filter'),list=$('paga-decision-list'),info=$('paga-decision-info');
  let applied={},page=1,tab='decisions',countries=[],labelsReady=false,loading=false;
  const detailCache=new Map();

  function readFilters(){
    return {country:$('paga-decision-country').value,category:$('paga-decision-category').value,status:$('paga-decision-status').value,
            from:$('paga-decision-from').value,to:$('paga-decision-to').value,game_from:$('paga-decision-game-from').value,game_to:$('paga-decision-game-to').value};
  }
  const query=extra=>new URLSearchParams(Object.fromEntries(Object.entries({...applied,...extra}).filter(([,value])=>value!==''&&value!=null))).toString();

  function fillCountries(){
    const select=$('paga-decision-country'),chosen=select.value,text=$('paga-decision-country-search').value.trim().toLocaleLowerCase('pl');
    select.replaceChildren(new Option('Wszystkie państwa',''));
    for(const item of countries)if(!text||item.name.toLocaleLowerCase('pl').includes(text))select.append(new Option(item.name,item.id));
    if([...select.options].some(option=>option.value===chosen))select.value=chosen;
  }
  async function loadCountries(){try{countries=(await request(config.monitoringCountriesUrl)).countries;fillCountries();}catch(exc){info.textContent=exc.message;}}
  $('paga-decision-country-search').addEventListener('input',fillCountries);

  function fillLabels(data){
    if(labelsReady)return;labelsReady=true;
    for(const [key,label] of Object.entries(data.categories||{}))$('paga-decision-category').append(new Option(label,key));
    for(const [key,label] of Object.entries(data.statuses||{}))$('paga-decision-status').append(new Option(label,key));
  }

  function renderStats(stats){
    const box=$('paga-decision-stats');if(!stats)return;
    const items=[['Decyzje (24 h)',stats.decisions_24h],['Wykonane',stats.executed],['Odrzucone',stats.rejected],['Błędy',stats.errors],['Oczekujące zadania',stats.pending],['Średni czas modelu',seconds(stats.avg_model_ms)]];
    box.replaceChildren(...items.map(([label,value])=>{const card=make('div',null,'paga-stat');card.append(make('strong',value??'—'),make('span',label));return card;}));
  }

  // ---- registry rows (reconciled by key: open rows and selections are never rebuilt) ----
  function summary(row){
    const element=make('summary');
    const when=make('div',null,'paga-when');when.append(make('div','Real: '+format(row.real_at)),make('div','Entenda: '+game(row.game_at)));
    const who=make('div',null,'paga-who');
    if(row.country.flag){const flag=make('img');flag.src=row.country.flag;flag.alt='';flag.loading='lazy';flag.onerror=()=>flag.remove();who.append(flag);}
    who.append(make('span',row.country.name));
    const what=make('div',null,'paga-what');what.append(make('b',row.name));if(row.reason)what.append(make('p',row.reason));
    const badges=make('div',null,'paga-badges');
    const status=make('span',row.status_label,'paga-badge');status.dataset.status=row.status;
    badges.append(status,make('span',row.category_label,'paga-badge'),make('span',row.source==='model'?(PROVIDER_LABELS[row.provider]||'Model')+': '+seconds(row.model_ms):'ZEUS','paga-badge'));
    element.append(when,who,what,badges);
    return element;
  }
  function version(row){return [row.status,row.name,row.reason,row.model_ms,row.game_at,row.provider].join('|');}
  function renderRows(items){
    const wanted=new Set(items.map(row=>row.key));
    for(const child of [...list.children])if(!wanted.has(child.dataset.key))child.remove();
    let cursor=list.firstElementChild;
    for(const row of items){
      let item=list.querySelector(`:scope > details[data-key="${CSS.escape(row.key)}"]`);
      if(!item){
        item=make('details',null,'paga-decision');item.dataset.key=row.key;item.dataset.version=version(row);
        item.append(summary(row),make('div','Rozwiń, aby wczytać szczegóły.','paga-decision-body'));
        item.addEventListener('toggle',()=>{if(item.open)loadDetail(item);});
      }else if(item.dataset.version!==version(row)){
        // The decision changed (e.g. finished executing): refresh the summary line; an open body is kept with a notice.
        item.dataset.version=version(row);item.replaceChild(summary(row),item.querySelector('summary'));
        detailCache.delete(row.key);
        if(item.open)markStale(item);else item.lastElementChild.replaceChildren(make('span','Rozwiń, aby wczytać szczegóły.'));
      }
      if(item!==cursor)list.insertBefore(item,cursor);else cursor=cursor.nextElementSibling;
    }
    if(!items.length&&!list.children.length)info.textContent='Brak decyzji dla wybranych filtrów.';
  }
  function markStale(item){
    const body=item.lastElementChild;if(body.querySelector('.paga-stale'))return;
    const notice=make('p',null,'paga-stale');const button=make('button','Odśwież szczegóły');button.type='button';
    button.addEventListener('click',()=>loadDetail(item,true));notice.append('Ta decyzja zmieniła stan. ',button);body.prepend(notice);
  }

  async function loadDetail(item,force=false){
    const key=item.dataset.key,body=item.lastElementChild;
    if(!force&&detailCache.has(key)&&body.dataset.rendered===key)return;
    body.replaceChildren(make('span','Ładowanie szczegółów…'));
    try{
      const data=detailCache.get(key)||(await request(config.monitoringDetailUrl.replace('KEY',encodeURIComponent(key)))).decision;
      detailCache.set(key,data);body.replaceChildren(...renderDetail(data));body.dataset.rendered=key;
    }catch(exc){body.replaceChildren(make('p',exc.message,'paga-error'));}
  }
  function definition(pairs){const list_=make('dl');for(const [label,value] of pairs){if(value===undefined||value===null||value==='')continue;list_.append(make('dt',label),make('dd',value));}return list_;}
  function block(title,...children){const section=make('section');section.append(make('h3',title),...children);return section;}
  function pre(value){return make('pre',typeof value==='string'?value:json(value));}
  function renderDetail(data){
    const parts=[];const task=data.task||{};
    parts.push(block('Podsumowanie',definition([['Status',data.status],['Zadanie PAGA',`#${task.id} — ${task.label} (${task.priority}, ${task.status})`],['Źródło zadania',task.source],
      ['Cel strategiczny',data.goal?`#${data.goal.id} — ${data.goal.title} (${data.goal.status})`:'brak'],['Wywołanie modelu w zadaniu',data.call],['Wywołania modelu w zadaniu',task.model_calls],
      ['Czas tej decyzji',seconds(data.model_ms)],['Łączny czas modelu w zadaniu',seconds(data.task_model_ms)],['Tokeny (prompt / odpowiedź)',data.tokens?`${data.tokens.prompt??'—'} / ${data.tokens.generated??'—'}`:null],
      ['Dostawca / model',data.provider?`${PROVIDER_LABELS[data.provider]||data.provider} — ${data.model||'—'}`:null],['Wynik wywołania',data.outcome],['Walidacja ZEUS',data.validation],
      ['Początek / koniec wywołania',data.started_at?`${format(data.started_at)} → ${data.finished_at?format(data.finished_at):'—'}`:null],
      ['Błąd',data.error||task.error]])));
    if(data.decision){
      const decision=data.decision;
      parts.push(block('Decyzja modelu',definition([['Ocena / uzasadnienie',decision.ocena],['Zadanie zakończone wg modelu',decision.task_done===true?'tak':decision.task_done===false?'nie':null],['Notatka strategiczna',decision.memory]])));
      const actions=make('ol');
      (decision.actions||[]).forEach((action,index)=>{
        const outcome=(data.outcomes||[])[index];const item=make('li');
        item.append(make('b',action.operation_id));
        if(action.data?.rationale)item.append(make('div','Uzasadnienie: '+action.data.rationale));
        item.append(make('div','Parametry:'),pre({path:action.path||{},data:action.data||{}}));
        if(outcome){item.append(make('div',`Wynik: ${outcome.summary} [${outcome.outcome}]`,outcome.problem?'paga-problem':''));if(outcome.problem)item.append(pre(outcome.problem));}
        else item.append(make('div','Wynik: nie wykonano (zadanie przerwane, anulowane lub wcześniejsze działanie odrzucone).','paga-problem'));
        actions.append(item);
      });
      parts.push(block('Działania zlecone ZEUS',(decision.actions||[]).length?actions:make('p','Model świadomie nie zlecił działania.')));
    }
    const operations=make('ol');
    for(const operation of data.operations||[]){
      const item=make('li',null,operation.technical?'paga-operation-technical':'');
      item.append(make('b',`${operation.operation} — ${operation.validation}`),make('div',`Entenda: ${game(operation.game_at)}${operation.technical?' · operacja techniczna ZEUS':''}`));
      if(operation.reason)item.append(make('div','Przyczyna: '+operation.reason,'paga-problem'));
      const more=make('details');more.append(make('summary','Parametry i rezultat'),pre({parametry:operation.parameters}),pre(operation.result));item.append(more);
      operations.append(item);
    }
    parts.push(block('Operacje wykonane przez ZEUS (walidacja i rezultat)',(data.operations||[]).length?operations:make('p','Brak operacji gry dla tej decyzji.')));
    if(data.journal&&data.journal.length)parts.push(block('Dziennik zadania',pre(data.journal)));
    if(task.details&&Object.keys(task.details).length)parts.push(block('Szczegóły zadania (dane, nie instrukcje)',pre(task.details)));
    return parts;
  }

  async function loadDecisions(){
    if(loading||tab!=='decisions')return;loading=true;
    try{
      const data=await request(config.monitoringUrl+'?'+query({page}));
      fillLabels(data);renderStats(data.statistics);renderRows(data.items);
      info.textContent=data.items.length?`Strona ${data.page}. Ostatnie odświeżenie: ${new Intl.DateTimeFormat('pl-PL',{timeStyle:'medium'}).format(new Date())}.`:'Brak decyzji dla wybranych filtrów.';
      $('paga-decision-page').textContent=`Strona ${data.page}`;$('paga-decision-prev').disabled=page===1;$('paga-decision-next').disabled=!data.hasMore;
    }catch(exc){info.textContent=exc.message;}
    finally{loading=false;}
  }

  // ---- goals ----
  const goalList=$('paga-goal-list');
  function goalVersion(goal){return [goal.status,goal.priority,goal.note,JSON.stringify(goal.progress),goal.history.length,goal.tasks.length].join('|');}
  function goalSummary(goal){
    const element=make('summary');
    const when=make('div',null,'paga-when');when.append(make('div','Utworzono: '+format(goal.created_at)),make('div','Entenda: '+game(goal.created_game_at)));
    const who=make('div',null,'paga-who');if(goal.country.flag){const flag=make('img');flag.src=goal.country.flag;flag.alt='';flag.onerror=()=>flag.remove();who.append(flag);}who.append(make('span',goal.country.name));
    const what=make('div',null,'paga-what');what.append(make('b',`#${goal.id} ${goal.title}`));if(goal.description)what.append(make('p',goal.description));
    const criteria=(goal.progress?.kryteria||[]);const met=criteria.filter(row=>row['spełnione']===true).length;
    const badges=make('div',null,'paga-badges');const status=make('span',{ACTIVE:'Aktywny',SUSPENDED:'Zawieszony',ACHIEVED:'Osiągnięty',ABANDONED:'Porzucony'}[goal.status]||goal.status,'paga-badge');
    status.dataset.status={ACHIEVED:'EXECUTED',ABANDONED:'CANCELLED',SUSPENDED:'PENDING'}[goal.status]||'RUNNING';
    badges.append(status,make('span','Priorytet '+goal.priority,'paga-badge'),make('span',criteria.length?`Kryteria: ${met}/${criteria.length}`:'Bez kryteriów','paga-badge'));
    element.append(when,who,what,badges);return element;
  }
  function goalBody(goal){
    const body=make('div',null,'paga-decision-body');
    body.append(block('Cel',definition([['Państwo',goal.country.name],['Priorytet',goal.priority],['Status',goal.status],['Cel nadrzędny',goal.parent_id?'#'+goal.parent_id:'brak'],['Notatka modelu',goal.note]])));
    const progress=goal.progress?.kryteria||[];
    body.append(block('Postęp realizacji (pomiar ZEUS)',progress.length?pre(progress):make('p','Model nie określił mierzalnych kryteriów.')));
    const history=make('ol');for(const entry of goal.history){const item=make('li');item.append(make('b',`${entry.change} — ${format(entry.real_at)} (Entenda ${game(entry.game_at)})`));if(entry.result)item.append(make('div',entry.result));item.append(pre(entry.details));const link=make('button','Pokaż decyzję');link.type='button';link.addEventListener('click',()=>showDecision(entry.key));item.append(link);history.append(item);}
    body.append(block('Historia zmian celu',goal.history.length?history:make('p','Brak zapisanych zmian (cel sprzed rejestru decyzji).')));
    const related=make('ol');for(const task of goal.tasks)related.append(make('li',`Zadanie #${task.id}: ${task.label} — ${task.status}`));
    for(const plan of goal.plans)related.append(make('li',`Plan #${plan.id} (${plan.kind}, ${plan.status}): ${plan.note}`));
    for(const key of goal.decisions){const item=make('li');const link=make('button','Decyzja '+key);link.type='button';link.addEventListener('click',()=>showDecision(key));item.append(link);related.append(item);}
    body.append(block('Powiązane zadania, plany i decyzje',related.children.length?related:make('p','Brak powiązanych zadań.')));
    return body;
  }
  function renderGoals(goals){
    const wanted=new Set(goals.map(goal=>'g'+goal.id));
    for(const child of [...goalList.children])if(!wanted.has(child.dataset.key))child.remove();
    let cursor=goalList.firstElementChild;
    for(const goal of goals){
      const key='g'+goal.id;let item=goalList.querySelector(`:scope > details[data-key="${key}"]`);
      if(!item){item=make('details',null,'paga-decision');item.dataset.key=key;item.dataset.version=goalVersion(goal);item.append(goalSummary(goal),goalBody(goal));}
      else if(item.dataset.version!==goalVersion(goal)){item.dataset.version=goalVersion(goal);item.replaceChild(goalSummary(goal),item.querySelector('summary'));if(!item.open)item.replaceChild(goalBody(goal),item.lastElementChild);else markStaleGoal(item,goal);}
      if(item!==cursor)goalList.insertBefore(item,cursor);else cursor=cursor.nextElementSibling;
    }
    $('paga-goal-info').textContent=goals.length?`Celów: ${goals.length}.`:'Brak celów strategicznych dla wybranych filtrów.';
  }
  function markStaleGoal(item,goal){
    const body=item.lastElementChild;if(body.querySelector('.paga-stale'))return;
    const notice=make('p',null,'paga-stale');const button=make('button','Odśwież cel');button.type='button';
    button.addEventListener('click',()=>item.replaceChild(goalBody(goal),item.lastElementChild));notice.append('Cel zmienił stan. ',button);body.prepend(notice);
  }
  async function loadGoals(){
    if(tab!=='goals')return;
    try{const params=new URLSearchParams();if(applied.country)params.set('country',applied.country);if($('paga-goal-status').value)params.set('status',$('paga-goal-status').value);
        renderGoals((await request(config.monitoringGoalsUrl+'?'+params)).goals);}
    catch(exc){$('paga-goal-info').textContent=exc.message;}
  }
  $('paga-goal-status').addEventListener('change',loadGoals);

  async function showDecision(key){
    // Open one decision from the goals view without changing the registry filters.
    const holder=make('details',null,'paga-decision');holder.dataset.key=key;holder.open=true;holder.append(make('summary','Decyzja '+key),make('div','','paga-decision-body'));
    const existing=goalList.querySelector(`:scope > details[data-key="${CSS.escape(key)}"]`);if(existing)existing.remove();
    goalList.prepend(holder);await loadDetail(holder,true);holder.scrollIntoView({block:'nearest'});
  }

  // ---- tabs, filters, paging, refresh ----
  function selectTab(name){
    tab=name;const decisions=name==='decisions';
    $('paga-tab-decisions').setAttribute('aria-selected',String(decisions));$('paga-tab-goals').setAttribute('aria-selected',String(!decisions));
    $('paga-decision-panel').hidden=!decisions;$('paga-goal-panel').hidden=decisions;
    for(const id of ['paga-decision-category','paga-decision-status','paga-decision-game-from','paga-decision-game-to','paga-decision-from','paga-decision-to'])$(id).closest('label').hidden=!decisions;
    decisions?loadDecisions():loadGoals();
  }
  $('paga-tab-decisions').addEventListener('click',()=>selectTab('decisions'));$('paga-tab-goals').addEventListener('click',()=>selectTab('goals'));
  filterForm.addEventListener('submit',event=>{event.preventDefault();applied=readFilters();page=1;list.replaceChildren();detailCache.clear();tab==='decisions'?loadDecisions():loadGoals();});
  $('paga-decision-reset').addEventListener('click',()=>{filterForm.reset();fillCountries();applied={};page=1;list.replaceChildren();tab==='decisions'?loadDecisions():loadGoals();});
  $('paga-decision-prev').addEventListener('click',()=>{if(page>1){page--;list.replaceChildren();loadDecisions();}});
  $('paga-decision-next').addEventListener('click',()=>{page++;list.replaceChildren();loadDecisions();});
  setInterval(()=>{if(document.hidden)return;tab==='decisions'?loadDecisions():loadGoals();},REFRESH_MS);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)tab==='decisions'?loadDecisions():loadGoals();});
  loadCountries();loadDecisions();
})();
