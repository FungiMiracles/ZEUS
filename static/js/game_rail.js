/* 19 Nov 2026: zakładka „Komunikacja” — kolej. Wybór dwóch miast na mapie, wycena (2,5 mln ROI/km, 1 dzień na 50 km),
   budowa linii krajowej albo wniosek o współfinansowanie do sąsiada; tory jako cienka linia z poprzecznymi kreskami,
   w budowie — ikona żurawia z dymkiem (postęp i data ukończenia). */
(()=>{'use strict';
const node=document.getElementById('rail-config');if(!node)return;
const cfg=JSON.parse(node.textContent);
const $=id=>document.getElementById(id);
const make=(tag,text,cls)=>{const el=document.createElement(tag);if(text!=null)el.textContent=text;if(cls)el.className=cls;return el;};
const number=v=>Number(v||0).toLocaleString('pl-PL');
const km=v=>Math.round(Number(v||0)).toLocaleString('pl-PL')+' km';
const money=v=>{const n=Number(v||0);return n>=1e9?(n/1e9).toLocaleString('pl-PL',{maximumFractionDigits:2})+' MLD ROI':n>=1e6?(n/1e6).toLocaleString('pl-PL',{maximumFractionDigits:1})+' mln ROI':number(n)+' ROI';};
const date=v=>v?new Intl.DateTimeFormat('pl-PL',{timeZone:'UTC',dateStyle:'short',timeStyle:'short'}).format(new Date(v)):'—';
const coords=c=>L.latLng(c[1],c[0]);
let state=null,map=null,cityLayer=null,lineLayer=null,selected=[],currentQuote=null,busy=false,fitted=false,trainRun=null,trainKey='';

async function api(url,body){
  const options=body?{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':cfg.csrf},body:JSON.stringify(body)}:{cache:'no-store'};
  const response=await fetch(url,{credentials:'same-origin',...options});let data;
  try{data=await response.json();}catch{throw Error('Nie udało się połączyć z serwerem gry.');}
  if(!response.ok)throw Error(data.error||'Operacja nie powiodła się.');return data;
}

function cityById(id){return state.cities.find(c=>c.id===id);}

function railLine(path,line){
  const latlngs=path.map(p=>[p[1],p[0]]),group=L.layerGroup();
  const building=line&&line.status==='ACTIVE'&&!line.completed,pending=line&&line.status==='PENDING',preview=!line;
  const color=preview?'#b06d00':pending?'#7a8597':'#26313f';
  // Tor jak na mapie: cienka linia i poprzeczne kreski (podkłady).
  L.polyline(latlngs,{pane:'railLines',color,weight:2,opacity:building||pending?.75:1,dashArray:pending?'6 5':null,interactive:false}).addTo(group);
  L.polyline(latlngs,{pane:'railLines',color,weight:7,opacity:building||pending?.55:.95,dashArray:'1.5 9',lineCap:'butt',interactive:false}).addTo(group);
  if(line){
    const hit=L.polyline(latlngs,{pane:'railLines',color:'#000',weight:14,opacity:0}).addTo(group);
    hit.bindTooltip(()=>lineTip(line),{...TIP,sticky:true});
  }
  if(building||pending){
    const mid=latlngs[Math.floor(latlngs.length/2)];
    const icon=make('div',null,'rail-crane');const img=make('img');img.src=cfg.craneIcon;img.alt='';icon.append(img);
    L.marker(mid,{pane:'railCranes',icon:L.divIcon({html:icon,className:'rail-crane-marker',iconSize:[22,22],iconAnchor:[11,11]})})
      .bindTooltip(()=>lineTip(line),{...TIP,offset:[0,-10]}).addTo(group);
  }
  return group;
}

// 26 Nov 2026: dymki w nowym wyglądzie gry (jak kopalnie i fabryki): nagłówek, lista wartości z ikonami, notka.
const TIP={className:'mine-region-tooltip rail-tooltip',direction:'top'};
function tipBox(title,subtitle,rows,note){
  const box=make('div',null,'mine-tip'),head=make('div',null,'mine-tip-head');head.append(make('strong',title));if(subtitle)head.append(make('span',subtitle));box.append(head);
  if(rows.length){const list=make('div',null,'mine-tip-list');
    for(const [icon,label,value] of rows){const row=make('div',null,'mine-tip-row');if(icon){const img=make('img');img.src=icon;img.alt='';row.append(img);}row.append(make('span',label),make('strong',value));list.append(row);}
    box.append(list);}
  if(note)box.append(make('p',note,'mine-tip-note'));
  return box;
}
function lineStatus(line){
  if(line.status==='PENDING')return line.awaitingMe?'Czeka na Twoją decyzję':`Czeka na zgodę: ${line.partner}`;
  if(line.completed)return 'Linia ukończona';
  if(line.status==='ACTIVE')return `Budowa torów: ${line.progress}%`;
  return 'Wniosek odrzucony';
}
function lineTip(line){
  const share=line.shares?.[String(state.countryId)];
  const rows=[[cfg.railIcon,'Długość',km(line.distanceKm)],[cfg.moneyIcon,'Koszt całkowity',money(line.cost)]];
  if(line.partnerId&&share)rows.push([cfg.moneyIcon,'Twój udział',`${km(share.distanceKm)} · ${money(share.cost)}`]);
  if(line.status==='ACTIVE'&&!line.completed)rows.push([cfg.timeIcon,'Ukończenie',date(line.readyAt)]);
  return tipBox(`${line.cityAName} – ${line.cityBName}`,lineStatus(line),rows,line.partnerId?`Linia międzynarodowa: ${line.initiator} – ${line.partner}.`:'');
}

function drawLines(){
  lineLayer.clearLayers();
  for(const line of state.lines){if(line.status==='ACTIVE'||line.status==='PENDING')railLine(line.path,line).addTo(lineLayer);}
  if(currentQuote)railLine(currentQuote.path,null).addTo(lineLayer);
  // 19 Nov 2026: pociągi (120 km/h czasu gry) na ukończonych liniach — tworzone na nowo tylko, gdy zmienił się zestaw linii.
  const done=state.lines.filter(l=>l.status==='ACTIVE'&&l.completed),key=done.map(l=>l.id).join(',');
  if(window.GameRailTrains&&key!==trainKey){trainRun?.stop();trainKey=key;
    trainRun=window.GameRailTrains.trains(map,done,{pane:'railTrains',gameNow:state.gameNow,timeMultiplier:state.timeMultiplier,speed:state.trainSpeed});}
}

function drawCities(){
  cityLayer.clearLayers();const network=new Set(state.networkCities||[]);
  for(const city of state.cities){
    const chosen=selected.includes(city.id),inNetwork=network.has(city.id);   // 20 Nov 2026: zielony obrys — miasto liczone do bonusu
    const marker=L.circleMarker(coords(city.point),{pane:'railCities',radius:chosen?7.5:city.own?5:4,color:inNetwork?'#1f8a3b':'#22301f',weight:inNetwork?2.6:1.6,fillColor:chosen?'#E8B65C':city.own?'#ffffff':'#c9ced6',fillOpacity:1});
    const lines=state.lines.filter(l=>l.status==='ACTIVE'&&l.completed&&(l.cityA===city.id||l.cityB===city.id)).length;
    const note=inNetwork?'W spójnej sieci kolejowej — liczone do dochodów z kolei.':city.own?'Kliknij, aby wybrać miasto początkowe lub docelowe.':'Miasto sąsiada — może być celem linii współfinansowanej.';
    marker.bindTooltip(()=>tipBox(city.name,state.countries[String(city.countryId)]||'',[[cfg.cityIcon,'Ludność',`${number(city.population)}`],[cfg.railIcon,'Ukończone linie',number(lines)]],note),{...TIP,offset:[0,-6]});
    marker.on('click',()=>choose(city));marker.addTo(cityLayer);
  }
}

async function choose(city){
  if(busy)return;$('rail-error').textContent='';
  if(!state.available){$('rail-error').textContent='Budowa linii kolejowych wymaga technologii „Transport kolejowy”. Możesz rozpatrywać wnioski sąsiadów o współfinansowanie.';return;}
  if(!selected.length||selected.length===2){
    if(!city.own){$('rail-error').textContent='Miasto początkowe musi leżeć we własnym państwie.';return;}
    selected=[city.id];currentQuote=null;
  }else if(city.id===selected[0]){selected=[];currentQuote=null;}
  else selected=[selected[0],city.id];
  renderSelection();drawCities();drawLines();
  if(selected.length===2){
    busy=true;$('rail-quote').hidden=false;$('rail-quote').textContent='Wycena trasy…';
    try{currentQuote=await api(cfg.quoteUrl,{city_a:selected[0],city_b:selected[1]});}
    catch(error){currentQuote=null;$('rail-error').textContent=error.message;$('rail-quote').hidden=true;}
    finally{busy=false;}
    renderSelection();drawLines();
  }
}

function renderSelection(){
  const names=selected.map(id=>cityById(id)?.name||'');
  $('rail-selected').textContent=!selected.length?'Nie wybrano miast.':selected.length===1?`Miasto początkowe: ${names[0]}. Wybierz miasto docelowe.`:`Trasa: ${names[0]} – ${names[1]}`;
  $('rail-clear').hidden=!selected.length;
  const quote=$('rail-quote'),build=$('rail-build');build.hidden=!currentQuote;
  if(!currentQuote){if(selected.length<2)quote.hidden=true;return;}
  quote.hidden=false;quote.replaceChildren();
  const list=make('dl','', 'rail-quote-list');
  const add=(label,value)=>{const row=make('div');row.append(make('dt',label),make('dd',value));list.append(row);};
  add('Długość trasy',km(currentQuote.distanceKm));add('Koszt budowy',money(currentQuote.cost));add('Czas budowy',`${currentQuote.buildDays} dni Entendy`);
  if(currentQuote.partnerId){
    const own=currentQuote.shares[String(state.countryId)],other=currentQuote.shares[String(currentQuote.partnerId)];
    add('Twój udział',`${km(own.distanceKm)} · ${money(own.cost)}`);
    add(`Udział: ${state.countries[String(currentQuote.partnerId)]||'sąsiad'}`,`${km(other.distanceKm)} · ${money(other.cost)}`);
  }
  quote.append(list);
  build.textContent=currentQuote.partnerId?'Wyślij wniosek o współfinansowanie':'Zbuduj linię';
}

function renderLists(){
  $('rail-connected').textContent=`${number(state.connectedPopulation)} mieszk.`;
  $('rail-bonus').textContent=money(state.bonus)+(state.partnerBonusPercent?` (w tym +${state.partnerBonusPercent}% za połączenia z sieciami sąsiadów)`:'');   // 22 Nov 2026
  $('rail-funds').textContent=money(state.funds);   // 26 Nov 2026: wcześniej instrukcja trafiła do komentarza (zawsze „—”)
  const infra=$('rail-infrastructure');if(infra)infra.textContent=`${Number(state.railInfrastructure||0).toLocaleString('pl-PL',{maximumFractionDigits:1})} / 100`;
  const noTech=$('rail-no-tech');if(noTech)noTech.hidden=!!state.available;
  const requests=$('rail-requests'),lines=$('rail-lines');requests.replaceChildren();lines.replaceChildren();
  const pending=state.lines.filter(l=>l.status==='PENDING'),mine=pending.filter(l=>l.awaitingMe).length;
  $('rail-requests-count').textContent=pending.length?`${number(pending.length)}`+(mine?` · ${number(mine)} czeka na Twoją decyzję`:''):'Brak';
  if(!pending.length)requests.append(make('p','Brak wniosków. Wniosek powstaje, gdy wybierzesz trasę do miasta sąsiada.','rail-empty'));
  // 26 Nov 2026: wnioski jako karty decyzji — najpierw te, które czekają na decyzję gracza
  for(const line of [...pending].sort((a,b)=>Number(b.awaitingMe)-Number(a.awaitingMe))){
    const card=make('article',null,'rail-request-card'+(line.awaitingMe?' rail-request-incoming':''));
    const head=make('header');const img=make('img');img.src=cfg.railIcon;img.alt='';
    const title=make('div');title.append(make('strong',`${line.cityAName} – ${line.cityBName}`),make('span',line.awaitingMe?`Wniosek od: ${line.initiator}`:`Wniosek do: ${line.partner}`));
    head.append(img,title,make('span',line.awaitingMe?'Do decyzji':'Oczekuje','rail-request-badge'));card.append(head);
    const list=make('dl');const add=(label,value)=>{const row=make('div');row.append(make('dt',label),make('dd',value));list.append(row);};
    const own=line.shares?.[String(state.countryId)],otherId=line.awaitingMe?line.initiatorId:line.partnerId,other=line.shares?.[String(otherId)];
    add('Długość trasy',km(line.distanceKm));add('Koszt całkowity',money(line.cost));
    if(own)add('Twój odcinek',`${km(own.distanceKm)} · ${money(own.cost)}`);
    if(other)add(`Odcinek: ${state.countries[String(otherId)]||'sąsiad'}`,`${km(other.distanceKm)} · ${money(other.cost)}`);
    add('Czas budowy',`${number(line.buildDays)} dni Entendy`);
    card.append(list);
    const actions=make('div',null,'rail-row-actions');
    const act=(label,action,cls)=>{const b=make('button',label,cls);b.type='button';b.addEventListener('click',()=>decide(line,action));actions.append(b);};
    if(line.awaitingMe){act('Akceptuj i współfinansuj','accept','rail-primary');act('Odrzuć','reject');}else if(line.own)act('Wycofaj wniosek','cancel');
    card.append(actions);requests.append(card);
  }
  const built=state.lines.filter(l=>l.status==='ACTIVE').sort((a,b)=>Number(a.completed)-Number(b.completed));
  const building=built.filter(l=>!l.completed).length;
  $('rail-lines-count').textContent=built.length?`(${number(built.length)}${building?` · w budowie ${number(building)}`:''})`:'';
  if(!built.length){lines.append(make('p','Brak linii kolejowych.','rail-empty'));return;}
  // 26 Nov 2026: zwinięta tabela zamiast bardzo długiej listy kart
  const table=make('table',null,'rail-lines-table'),thead=make('thead'),hr=make('tr');
  for(const label of ['Trasa','Długość','Koszt (Twój udział)','Stan'])hr.append(make('th',label));thead.append(hr);table.append(thead);
  const body=make('tbody');
  for(const line of built){
    const tr=make('tr');tr.append(make('th',`${line.cityAName} – ${line.cityBName}`),make('td',km(line.distanceKm)),make('td',money(line.shares?.[String(state.countryId)]?.cost??line.cost)));
    const cell=make('td');
    if(line.completed)cell.append(make('span','Ukończona','rail-done'));
    else{const bar=make('progress');bar.max=100;bar.value=line.progress;bar.setAttribute('aria-label','Postęp budowy');cell.append(bar,make('span',` ${line.progress}% · ${date(line.readyAt)}`));}
    tr.append(cell);body.append(tr);
  }
  table.append(body);lines.append(table);
}

async function decide(line,action){
  if(busy)return;busy=true;$('rail-error').textContent='';
  try{await api(cfg.changeUrl,{action,line_id:line.id});await refresh();}
  catch(error){$('rail-error').textContent=error.message;}finally{busy=false;}
}

$('rail-clear').addEventListener('click',()=>{selected=[];currentQuote=null;$('rail-error').textContent='';renderSelection();drawCities();drawLines();});
$('rail-build').addEventListener('click',async()=>{
  if(busy||!currentQuote)return;busy=true;$('rail-error').textContent='';
  try{
    await api(cfg.changeUrl,{action:'build',city_a:currentQuote.cityA,city_b:currentQuote.cityB,expected_cost:currentQuote.cost,request_id:crypto.randomUUID?crypto.randomUUID():String(Date.now())+Math.random()});
    selected=[];currentQuote=null;await refresh();
  }catch(error){$('rail-error').textContent=error.message;}finally{busy=false;}
});

async function refresh(){state=await api(cfg.stateUrl);renderSelection();renderLists();if(map){drawCities();drawLines();fit();}}

function fit(){
  // 20 Nov 2026: bez stanu (zakładka otwarta przed odpowiedzią serwera) i przy zerowym rozmiarze kontenera (telefon, układ
  // jeszcze niepoliczony) nie dopasowujemy — wcześniej fitBounds na 0×0 px trwale psuł widok mapy.
  if(fitted||!map||!state)return;const size=map.getSize();if(!size.x||!size.y)return;const own=state.cities.filter(c=>c.own);if(!own.length)return;
  const bounds=L.latLngBounds(own.map(c=>coords(c.point)));
  if(bounds.isValid()){map.fitBounds(bounds.pad(.25),{maxZoom:4,animate:false});fitted=true;}
}

function init(){
  if(map||!window.L)return;
  map=L.map('rail-map',{crs:L.CRS.Simple,minZoom:-10,maxZoom:8,zoomSnap:.25,attributionControl:false});
  fetch(cfg.countriesUrl,{credentials:'same-origin'}).then(r=>r.json()).then(countries=>{
    const near=new Set((state?.neighbors||[]).map(Number));
    L.geoJSON(countries,{coordsToLatLng:coords,interactive:false,style:f=>{const id=Number(f.properties?.panstwo_id);
      return {color:'#667C63',weight:1,fillOpacity:1,fillColor:id===cfg.countryId?'#B8C9B0':near.has(id)?'#DCE3D4':'#F1F2EE'};}}).addTo(map).bringToBack();
  }).catch(()=>{});
  // 19 Nov 2026: miasta w osobnej warstwie nad torami — wcześniej po odświeżeniu tory (z szerokim, niewidocznym pasem
  // dymka) rysowały się na wierzchu i przechwytywały kliknięcie w miasto końcowe zbudowanej linii.
  map.createPane('railLines').style.zIndex='410';map.createPane('railTrains').style.zIndex='420';map.getPane('railTrains').style.pointerEvents='none';map.createPane('railCranes').style.zIndex='430';map.createPane('railCities').style.zIndex='450';   // żuraw pod miastami — nie zasłania kliknięcia
  lineLayer=L.layerGroup().addTo(map);cityLayer=L.layerGroup().addTo(map);
  if(state){drawCities();drawLines();fit();}
  if(window.ResizeObserver)new ResizeObserver(()=>{map.invalidateSize();fit();}).observe($('rail-map'));
}

// Mapa tworzona przy pierwszym otwarciu zakładki (ukryty kontener ma zerowy rozmiar).
const tab=$('infrastructure-tab-communication');
const open=()=>requestAnimationFrame(()=>{init();map?.invalidateSize();fit();});
tab?.addEventListener('click',open);
if(!$('infrastructure-communication-panel')?.hidden)open();
refresh().catch(error=>{$('rail-error').textContent=error.message;});
setInterval(()=>{if(!busy&&!document.hidden&&!$('infrastructure-communication-panel')?.hidden)refresh().catch(()=>{});},30000);
})();
