(()=>{'use strict';
// 14 Nov 2026: „Panel administratora” — okno z hasłem; po poprawnym haśle przejście do ZEUS WIKI.
(()=>{const open=document.getElementById('sidebar-admin-open'),dialog=document.getElementById('sidebar-admin-dialog');if(!open||!dialog)return;
  const form=document.getElementById('sidebar-admin-form'),input=document.getElementById('sidebar-admin-password'),error=document.getElementById('sidebar-admin-error'),submit=document.getElementById('sidebar-admin-submit');
  const show=text=>{error.textContent=text||'';error.hidden=!text;};
  open.addEventListener('click',()=>{form.reset();show('');dialog.showModal();input.focus();});
  document.getElementById('sidebar-admin-cancel').addEventListener('click',()=>dialog.close());
  form.addEventListener('submit',async event=>{event.preventDefault();submit.disabled=true;show('');
    try{const response=await fetch(form.action,{method:'POST',body:new FormData(form),credentials:'same-origin',headers:{Accept:'application/json'}});
      const data=await response.json().catch(()=>({}));
      if(response.ok&&data.redirect){window.location.assign(data.redirect);return;}
      show(data.error||'Nie udało się zweryfikować hasła.');input.select();
    }catch(_){show('Brak połączenia z serwerem. Spróbuj ponownie.');}
    finally{submit.disabled=false;}});
})();
// 13 Nov 2026: tooltipy lewego paska (wycinki budżetu, skrzynie magazynu) i dopasowanie plakietek z liczbami.
const bar=document.querySelector('.game-sidebar');if(!bar)return;
// 13 Nov 2026: wysokość przyklejonego menu → pasek boczny zaczyna się pod nim
(()=>{const nav=document.querySelector('.game-navigation');if(!nav)return;const set=()=>document.documentElement.style.setProperty('--game-nav-height',nav.getBoundingClientRect().height+'px');
  set();if(window.ResizeObserver)new ResizeObserver(set).observe(nav);window.addEventListener('resize',set);})();
// 13 Nov 2026: powiadomienia i wiadomości prywatne obok flagi na pasku — na komputerze i w wysuwanym pasku na telefonie.
// Pozycję listy powiadomień ustala game_ui.js (na prawo od ikony na komputerze, pod ikoną na telefonie).
(()=>{const slot=document.getElementById('sidebar-tools'),notes=document.getElementById('game-notifications'),mail=document.getElementById('game-mail-toggle');
  if(slot&&notes&&mail)slot.append(notes,mail);})();
// 13 Nov 2026: telefon — pasek wysuwany z lewej strony zakładką ze strzałką.
(()=>{const tab=document.getElementById('sidebar-drawer-tab'),backdrop=document.getElementById('sidebar-drawer-backdrop');if(!tab)return;
  const mobile=window.matchMedia('(max-width:900px)'),notes=document.getElementById('game-notifications');
  function setOpen(open){bar.classList.toggle('is-open',open);document.body.classList.toggle('sidebar-drawer-open',open);tab.setAttribute('aria-expanded',String(open));
    tab.setAttribute('aria-label',open?'Schowaj pasek państwa':'Pokaż pasek państwa');if(backdrop)backdrop.hidden=!open;
    if(mobile.matches)bar.inert=!open;if(!open&&notes)notes.open=false;}
  function sync(){if(mobile.matches)setOpen(bar.classList.contains('is-open'));else{bar.inert=false;bar.classList.remove('is-open');document.body.classList.remove('sidebar-drawer-open');if(backdrop)backdrop.hidden=true;}}
  tab.addEventListener('click',()=>setOpen(!bar.classList.contains('is-open')));
  backdrop?.addEventListener('click',()=>setOpen(false));
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&bar.classList.contains('is-open')&&!document.querySelector('dialog[open]')){setOpen(false);tab.focus();}});
  sync();mobile.addEventListener?mobile.addEventListener('change',sync):mobile.addListener(sync);
  // Kropka na zakładce, gdy są nieprzeczytane powiadomienia lub wiadomości.
  const badges=[document.getElementById('game-notification-count'),document.getElementById('game-mail-count')].filter(Boolean);
  const unread=()=>tab.classList.toggle('has-unread',badges.some(badge=>!badge.hidden&&badge.textContent.trim()!==''&&badge.textContent.trim()!=='0'));
  for(const badge of badges)new MutationObserver(unread).observe(badge,{attributes:true,childList:true,characterData:true,subtree:true});unread();})();
const tip=document.createElement('div');tip.className='sidebar-floating-tip';tip.hidden=true;tip.setAttribute('role','tooltip');document.body.append(tip);
function show(target,build){tip.replaceChildren();build(tip);tip.hidden=false;const rect=target.getBoundingClientRect(),box=tip.getBoundingClientRect();
  let left=rect.right+10,top=rect.top+rect.height/2-box.height/2;if(left+box.width>window.innerWidth-8)left=Math.max(8,rect.left-box.width-10);
  top=Math.min(Math.max(8,top),window.innerHeight-box.height-8);tip.style.left=left+'px';tip.style.top=top+'px';}
function hide(){tip.hidden=true;}
const line=(tag,text,cls)=>{const node=document.createElement(tag);node.textContent=text;if(cls)node.className=cls;return node;};
for(const slice of bar.querySelectorAll('.sidebar-pie-slice')){
  const build=box=>{box.append(line('strong',slice.dataset.label),line('span','Do wykorzystania: '+slice.dataset.remaining),line('small',`${String(slice.dataset.share).replace('.',',')}% środków do wydania · przydział: ${slice.dataset.allocated} · wydano: ${slice.dataset.spent}`));};
  slice.querySelector('title')?.remove();
  slice.addEventListener('mouseenter',()=>show(slice,build));slice.addEventListener('focus',()=>show(slice,build));
  slice.addEventListener('mouseleave',hide);slice.addEventListener('blur',hide);}
for(const crate of bar.querySelectorAll('.warehouse-crate')){
  const source=crate.querySelector('.crate-tooltip');if(!source)continue;
  const build=box=>{for(const node of source.children)box.append(node.cloneNode(true));};
  crate.addEventListener('mouseenter',()=>show(crate,build));crate.addEventListener('focus',()=>show(crate,build));
  crate.addEventListener('mouseleave',hide);crate.addEventListener('blur',hide);}
bar.addEventListener('scroll',hide,{passive:true});
function fit(){for(const badge of bar.querySelectorAll('.crate-badge')){badge.style.fontSize='15px';const width=badge.getBoundingClientRect().width;if(badge.scrollWidth>width&&width>0)badge.style.fontSize=Math.max(9,15*width/badge.scrollWidth)+'px';}}
if(window.ResizeObserver)new ResizeObserver(fit).observe(bar);fit();})();
