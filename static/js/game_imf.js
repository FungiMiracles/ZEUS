// 18 Nov 2026: Międzynarodowy Fundusz Walutowy — ekran funduszu (#imf-root) i panel spłaty na ekranie budżetu (#imf-debt).
(()=>{'use strict';
const money=value=>window.GameMoney?window.GameMoney.format(value):String(value);
const make=(tag,text,cls)=>{const el=document.createElement(tag);if(text!=null)el.textContent=text;if(cls)el.className=cls;return el;};
const svgNS='http://www.w3.org/2000/svg';
const cents=value=>{const m=/^(-?)(\d+)(?:\.(\d{1,2}))?$/.exec(String(value??'0'));if(!m)return 0n;const v=BigInt(m[2])*100n+BigInt((m[3]||'').padEnd(2,'0')||'0');return m[1]?-v:v;};
// Kwota w MLD (do 9 miejsc po przecinku) → całkowita liczba ROI jako tekst.
function mldToRoi(text){const m=/^\s*(\d+)(?:[.,](\d{1,9}))?\s*$/.exec(String(text));if(!m)throw Error('Podaj kwotę w miliardach, np. 12 albo 12,5.');const v=BigInt(m[1])*1000000000n+BigInt((m[2]||'').padEnd(9,'0'));if(v<1n)throw Error('Podaj dodatnią kwotę.');return v.toString();}
function slicePath(cx,cy,r,ri,start,end){const p=(radius,a)=>[cx+radius*Math.cos(a),cy+radius*Math.sin(a)];const large=end-start>Math.PI?1:0;const [x1,y1]=p(r,start),[x2,y2]=p(r,end),[x3,y3]=p(ri,end),[x4,y4]=p(ri,start),f=v=>v.toFixed(2);return `M${f(x1)} ${f(y1)}A${f(r)} ${f(r)} 0 ${large} 1 ${f(x2)} ${f(y2)}L${f(x3)} ${f(y3)}A${f(ri)} ${f(ri)} 0 ${large} 0 ${f(x4)} ${f(y4)}Z`;}
function percent(part,total){if(total<=0n)return '0,0';const tenths=(part*1000n+total/2n)/total;return `${tenths/10n},${tenths%10n}`;}
function flagImg(src){const img=make('img');img.src=src;img.alt='';img.width=28;img.height=19;img.className='imf-flag';img.onerror=()=>{img.hidden=true;};return img;}
function makePost(root){return async data=>{const response=await fetch(root.dataset.changeUrl,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':root.dataset.csrf},body:JSON.stringify(data)});const body=await response.json().catch(()=>({}));if(!response.ok)throw Error(body.error||'Nie udało się wykonać operacji.');return body;};}
async function load(root){const response=await fetch(root.dataset.stateUrl,{credentials:'same-origin',cache:'no-store'});const body=await response.json().catch(()=>({}));if(!response.ok)throw Error(body.error||'Nie udało się wczytać danych MFW.');return body;}
const STATUS={active:'do spłaty',repaid:'spłacona',rejected:'odrzucony'};
function loanRow(loan){const row=make('article',null,'imf-loan imf-loan-'+loan.status+(loan.overdue?' is-overdue':''));
  const head=make('div',null,'imf-loan-head');head.append(make('strong',`#${loan.id} · ${money(loan.amount)}`),make('span',loan.overdue?'zaległa':STATUS[loan.status]||loan.status,'imf-loan-status'));row.append(head);
  if(loan.status==='active')row.append(make('p',`Pozostało do spłaty: ${money(loan.outstanding)} · termin: zatwierdzenie budżetu za ${loan.due}`+(loan.periodsLeft?` (za ${loan.periodsLeft} ${loan.periodsLeft===1?'cykl':'cykle'})`:'')));
  if(loan.status!=='rejected'&&Number(loan.interestRate)>0)row.append(make('p',`Odsetki: ${Number(loan.interestRate).toLocaleString('pl-PL')}% za cykl budżetowy · naliczone dotąd: ${money(loan.interest||'0')}`));
  else if(loan.status==='repaid')row.append(make('p',`Termin był: ${loan.due}`));
  if(loan.reason)row.append(make('p',loan.reason,'imf-loan-reason'));
  return row;}

// ---------- ekran MFW ----------
function poolChart(container,state){container.replaceChildren();const pool=cents(state.pool),lent=cents(state.lent),left=pool-lent;
  const items=[{label:'Pozostało w funduszu',value:left,color:'#7fae6b'},{label:'Pożyczono państwom',value:lent,color:'#1E3A5F'}].filter(i=>i.value>0n);
  const wrapper=make('div',null,'finance-pie-chart'),pie=make('div',null,'finance-pie'),svg=document.createElementNS(svgNS,'svg');svg.setAttribute('viewBox','0 0 200 200');svg.setAttribute('role','img');
  svg.setAttribute('aria-label',`Środki MFW w roku ${state.year}: pozostało ${money(state.remaining)} z ${money(state.pool)}`);
  let angle=-Math.PI/2;const total=items.reduce((s,i)=>s+i.value,0n)||1n;
  items.forEach(item=>{let share=Number(item.value*100000n/total)/100000;if(items.length===1)share=.99999;const end=angle+share*2*Math.PI;const path=document.createElementNS(svgNS,'path');path.setAttribute('d',slicePath(100,100,97,97*.56,angle,end));path.setAttribute('fill',item.color);path.setAttribute('class','finance-pie-slice');const title=document.createElementNS(svgNS,'title');title.textContent=`${item.label}: ${money((item.value/100n).toString())}`;path.append(title);svg.append(path);angle=end;});
  const center=make('div',null,'finance-pie-center');center.append(make('span','Pozostało'),make('strong',money(state.remaining)));pie.append(svg,center);
  const legend=make('ul',null,'finance-pie-legend');
  for(const [label,value,color] of [['Pula na rok '+state.year,pool,null],['Pozostało w funduszu',left,'#7fae6b'],['Pożyczono państwom',lent,'#1E3A5F']]){const li=make('li'),dot=make('span',null,'finance-budget-dot');if(color)dot.style.backgroundColor=color;else dot.style.visibility='hidden';const name=make('span',label,'finance-pie-name'),val=make('span',`${money((value/100n).toString())}`+(color?` · ${percent(value,pool)}%`:''),'finance-pie-value');li.append(dot,name,val);legend.append(li);}
  wrapper.append(pie,legend);container.append(wrapper);}
function renderScreen(root,state){
  root.querySelector('#imf-year').textContent=state.year;root.querySelectorAll('[data-imf-year]').forEach(el=>{el.textContent=state.year;});
  poolChart(root.querySelector('#imf-pool-chart'),state);
  root.querySelectorAll('[data-imf]').forEach(el=>{el.textContent=money(state.credit[el.dataset.imf]??'0');});
  const form=root.querySelector('#imf-request-form');form.querySelector('button').disabled=!state.credit.hasBudget||cents(state.credit.maxLoan)<100000000000n;
  if(!state.credit.hasBudget)root.querySelector('#imf-status').textContent='Najpierw zatwierdź budżet państwa — MFW ocenia zdolność kredytową na jego podstawie.';
  else if(state.credit.activeLoan)root.querySelector('#imf-status').textContent='Państwo ma niespłaconą pożyczkę w MFW — nową możesz zaciągnąć dopiero po jej spłacie (ekran „Podatki i budżet”).';
  const body=root.querySelector('#imf-borrowers');body.replaceChildren();
  if(!state.borrowers.length){const tr=make('tr'),td=make('td','Żadne państwo nie jest obecnie zadłużone w MFW.');td.colSpan=3;tr.append(td);body.append(tr);}
  for(const b of state.borrowers){const tr=make('tr');if(b.countryId===state.countryId)tr.className='is-own';const th=make('th');th.scope='row';const name=make('span',null,'imf-country');name.append(flagImg(b.flag),make('span',b.name));th.append(name);tr.append(th,make('td',money(b.borrowedYear)),make('td',money(b.outstanding)));body.append(tr);}
  const list=root.querySelector('#imf-own-list');list.replaceChildren();if(!state.loans.length)list.append(make('p','Twoje państwo nie składało jeszcze wniosków do MFW.'));for(const loan of state.loans)list.append(loanRow(loan));}
function initScreen(root){const post=makePost(root),status=root.querySelector('#imf-status'),error=root.querySelector('#imf-error');let requestId=crypto.randomUUID();
  const refresh=()=>load(root).then(state=>{error.hidden=true;renderScreen(root,state);}).catch(e=>{error.textContent=e.message;error.hidden=false;});
  root.querySelector('#imf-request-form').addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget,button=form.querySelector('button');button.disabled=true;status.textContent='';
    try{const amount=window.GameMoney.fromBillions(form.elements.amount.value);const result=await post({action:'request',amount,request_id:requestId});requestId=crypto.randomUUID();
      status.textContent=result.status==='active'?`MFW przyznał pożyczkę ${money(result.amount)}. Środki wpłynęły do rezerwy budżetowej.`:`MFW odrzucił wniosek. ${result.reason||''}`;status.classList.toggle('imf-error',result.status!=='active');if(result.status==='active')form.elements.amount.value='';}
    catch(e){status.textContent=e.message;status.classList.add('imf-error');}finally{await refresh();}});
  refresh();}

// ---------- panel spłaty na ekranie „Podatki i budżet” ----------
function initDebt(root){const post=makePost(root),status=root.querySelector('#imf-debt-status'),form=root.querySelector('#imf-repay-form');let requestId=crypto.randomUUID();
  const render=state=>{root.querySelectorAll('[data-imf]').forEach(el=>{el.textContent=money(state[el.dataset.imf]??'0');});const list=root.querySelector('#imf-debt-loans');list.replaceChildren();
    const active=state.loans.filter(l=>l.status==='active');if(!active.length)list.append(make('p','Brak zadłużenia w MFW.'));for(const loan of active)list.append(loanRow(loan));
    form.hidden=!active.length;if(cents(state.dueNow)>0n)list.prepend(make('p',`Zaległość do pobrania przy najbliższym zatwierdzeniu budżetu: ${money(state.dueNow)}.`,'imf-message imf-error'));};
  const refresh=()=>load(root).then(render).catch(e=>{status.textContent=e.message;});
  const pay=async amount=>{status.textContent='';status.classList.remove('imf-error');form.querySelectorAll('button').forEach(b=>{b.disabled=true;});
    try{const result=await post({action:'repay',amount,request_id:requestId});requestId=crypto.randomUUID();form.elements.amount.value='';status.textContent=`Spłacono ${money(result.repaid)}. Pozostały dług: ${money(result.remaining)}.`;
      document.dispatchEvent(new CustomEvent('game:reserve-changed'));}
    catch(e){status.textContent=e.message;status.classList.add('imf-error');}finally{form.querySelectorAll('button').forEach(b=>{b.disabled=false;});await refresh();}};
  form.addEventListener('submit',event=>{event.preventDefault();let amount;try{amount=mldToRoi(form.elements.amount.value);}catch(e){status.textContent=e.message;status.classList.add('imf-error');return;}pay(amount);});
  root.querySelector('#imf-repay-all').addEventListener('click',()=>{if(window.confirm('Spłacić całe zadłużenie w MFW z rezerwy budżetowej?'))pay('all');});
  refresh();}

const start=()=>{const screen=document.getElementById('imf-root');if(screen)initScreen(screen);const debt=document.getElementById('imf-debt');if(debt)initDebt(debt);};
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start);else start();
})();
