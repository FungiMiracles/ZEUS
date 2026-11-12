(() => {
  'use strict';
  const root=document.getElementById('paga-relationships'),node=document.getElementById('paga-config');
  if(!root||!node)return;
  const config=JSON.parse(node.textContent);
  const get=name=>document.getElementById('paga-relationship-'+name);
  const form=get('form'),first=get('first'),second=get('second'),status=get('status'),satellite=get('satellite');
  const message=get('message'),error=get('error'),save=get('save'),reload=get('reload');
  const descriptions={
    none:'Brak dodatkowej sugestii dla tej pary. Zapis tej opcji usuwa obowiązującą sugestię.',
    satellite:'Wskaż państwo uległe. Drugie państwo będzie jego silniejszym patronem. Qwen preferuje utrzymanie tej zależności, ale może od niej odstąpić.',
    historical_ally:'Bardzo silna preferencja utrzymania sojuszu. Wojna, działania hybrydowe i sabotaż wobec sojusznika powinny być wyjątkowo rzadkie.',
    historical_hostile:'Bardzo silna preferencja utrzymania historycznego dystansu. Poprawa stosunków powinna być wyjątkowo rzadka, ale pozostaje możliwa.'
  };
  let revision=0,generation=0,ready=false,saving=false,loaded=false,page=1,listGeneration=0;
  async function request(url,options={}){
    const response=await fetch(url,{...options,credentials:'same-origin',cache:'no-store',headers:{'X-CSRF-Token':config.csrf,'X-PAGA-Access':config.access,...options.headers}});
    const data=await response.json().catch(()=>null);
    if(!response.ok){const failure=Error(data?.error||'Nie udało się odczytać lub zapisać powiązań. Otwórz panel ponownie, jeśli dostęp wygasł.');failure.status=response.status;throw failure;}
    return data;
  }
  function describe(){
    get('direction').hidden=status.value!=='satellite';
    satellite.required=status.value==='satellite';
    get('description').textContent=descriptions[status.value]||'';
  }
  function controls(){
    first.disabled=second.disabled=saving||!loaded;
    status.disabled=satellite.disabled=saving||!ready;
    save.disabled=saving||!ready;
    reload.disabled=saving||!first.value||!second.value||first.value===second.value;
  }
  function pairUrl(){return config.relationshipsUrl+'/'+first.value+'/'+second.value;}
  async function loadPair(){
    const current=++generation;ready=false;revision=0;message.textContent='';error.textContent='';
    status.value='none';satellite.replaceChildren(new Option('Wskaż państwo uległe',''));
    describe();controls();
    if(!first.value||!second.value)return;
    if(first.value===second.value){error.textContent='Wybierz dwa różne państwa.';return;}
    const firstName=first.selectedOptions[0].textContent,secondName=second.selectedOptions[0].textContent;
    satellite.append(new Option(firstName+' — satelita państwa '+secondName,first.value),new Option(secondName+' — satelita państwa '+firstName,second.value));
    try{
      const data=await request(pairUrl());if(current!==generation)return;
      revision=data.relationship.revision;status.value=data.relationship.status;
      satellite.value=data.relationship.satelliteId===null?'':String(data.relationship.satelliteId);
      ready=true;describe();
    }catch(exc){if(current===generation)error.textContent=exc.message;}
    finally{if(current===generation)controls();}
  }
  async function loadList(){
    const current=++listGeneration;
    try{
      const data=await request(config.relationshipsUrl+'?'+new URLSearchParams({page}));
      if(current!==listGeneration)return;
      const list=get('list');list.replaceChildren();
      if(!data.relationships.length){const empty=document.createElement('p');empty.textContent='Brak zapisanych sugestii na tej stronie.';list.append(empty);}
      for(const item of data.relationships){
        const row=document.createElement('div');row.className='paga-relationship-row';
        const text=document.createElement('span');
        text.textContent=item.status==='satellite'?
          (item.satelliteId===item.first.id?item.first.name:item.second.name)+' → satelita państwa '+(item.satelliteId===item.first.id?item.second.name:item.first.name):
          item.first.name+' ↔ '+item.second.name+' — '+data.statuses[item.status];
        const edit=document.createElement('button');edit.type='button';edit.textContent='Edytuj';
        edit.disabled=saving;edit.addEventListener('click',()=>{if(saving)return;first.value=String(item.first.id);second.value=String(item.second.id);loadPair();});
        row.append(text,edit);list.append(row);
      }
      get('prev').disabled=page<=1;get('next').disabled=!data.hasMore;
    }catch(exc){if(current===listGeneration)error.textContent=exc.message;}
  }
  async function initialize(){
    if(loaded)return;
    try{
      const data=await request(config.relationshipCountriesUrl);
      for(const select of [first,second]){
        select.replaceChildren(new Option('Wybierz państwo',''));
        for(const country of data.countries)select.append(new Option(country.name,String(country.id)));
      }
      loaded=true;controls();await loadList();
    }catch(exc){error.textContent=exc.message;}
  }
  first.addEventListener('change',loadPair);second.addEventListener('change',loadPair);
  status.addEventListener('change',describe);reload.addEventListener('click',loadPair);
  root.addEventListener('toggle',()=>{if(root.open)initialize();});
  get('prev').addEventListener('click',()=>{page=Math.max(1,page-1);loadList();});
  get('next').addEventListener('click',()=>{page++;loadList();});
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(saving||!ready||!form.reportValidity())return;
    const url=pairUrl(),payload={revision,status:status.value,satelliteId:status.value==='satellite'?Number(satellite.value):null};
    saving=true;controls();error.textContent='';message.textContent='Zapisywanie…';
    try{
      const data=await request(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      revision=data.relationship.revision;
      message.textContent=data.relationship.status==='none'?'Usunięto sugestię dla tej pary państw.':'Zapisano powiązanie. Qwen uwzględni je przy kolejnej decyzji.';
      page=1;await loadList();
    }catch(exc){message.textContent='';error.textContent=exc.message;ready=false;}
    finally{saving=false;controls();get('list').querySelectorAll('button').forEach(button=>button.disabled=false);}
  });
  describe();
})();
