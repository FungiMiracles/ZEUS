(()=>{'use strict';
// 13 Nov 2026: tooltipy lewego paska (wycinki budżetu, skrzynie magazynu) i dopasowanie plakietek z liczbami.
const bar=document.querySelector('.game-sidebar');if(!bar)return;
const tip=document.createElement('div');tip.className='sidebar-floating-tip';tip.hidden=true;tip.setAttribute('role','tooltip');document.body.append(tip);
function show(target,build){tip.replaceChildren();build(tip);tip.hidden=false;const rect=target.getBoundingClientRect(),box=tip.getBoundingClientRect();
  let left=rect.right+10,top=rect.top+rect.height/2-box.height/2;if(left+box.width>window.innerWidth-8)left=Math.max(8,rect.left-box.width-10);
  top=Math.min(Math.max(8,top),window.innerHeight-box.height-8);tip.style.left=left+'px';tip.style.top=top+'px';}
function hide(){tip.hidden=true;}
const line=(tag,text,cls)=>{const node=document.createElement(tag);node.textContent=text;if(cls)node.className=cls;return node;};
for(const slice of bar.querySelectorAll('.sidebar-pie-slice')){
  const build=box=>{box.append(line('strong',slice.dataset.label),line('span','Do wykorzystania: '+slice.dataset.remaining),line('small',`Przydział: ${slice.dataset.allocated} (${String(slice.dataset.share).replace('.',',')}% budżetu) · wydano: ${slice.dataset.spent}`));};
  slice.querySelector('title')?.remove();
  slice.addEventListener('mouseenter',()=>show(slice,build));slice.addEventListener('focus',()=>show(slice,build));
  slice.addEventListener('mouseleave',hide);slice.addEventListener('blur',hide);}
for(const crate of bar.querySelectorAll('.warehouse-crate')){
  const source=crate.querySelector('.crate-tooltip');if(!source)continue;
  const build=box=>{for(const node of source.children)box.append(node.cloneNode(true));};
  crate.addEventListener('mouseenter',()=>show(crate,build));crate.addEventListener('focus',()=>show(crate,build));
  crate.addEventListener('mouseleave',hide);crate.addEventListener('blur',hide);}
bar.addEventListener('scroll',hide,{passive:true});
function fit(){for(const badge of bar.querySelectorAll('.crate-badge')){badge.style.fontSize='10px';const width=badge.getBoundingClientRect().width;if(badge.scrollWidth>width&&width>0)badge.style.fontSize=Math.max(7,10*width/badge.scrollWidth)+'px';}}
if(window.ResizeObserver)new ResizeObserver(fit).observe(bar);fit();})();
