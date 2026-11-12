(()=>{'use strict';
// 12 Nov 2026: plakietki z liczbą na skrzyniach — czcionka zmniejszana, gdy liczba nie mieści się na skrzyni;
// tooltip przesuwany do środka, gdy wychodzi poza panel magazynu.
const shelves=document.querySelector('.warehouse-shelves');if(!shelves)return;
function fit(){for(const badge of shelves.querySelectorAll('.crate-badge')){badge.style.fontSize='11px';const width=badge.getBoundingClientRect().width;if(badge.scrollWidth>width&&width>0)badge.style.fontSize=Math.max(7,11*width/badge.scrollWidth)+'px';}}
function place(crate){const tip=crate.querySelector('.crate-tooltip');if(!tip)return;tip.style.left='50%';tip.style.transform='translateX(-50%)';
  const box=shelves.getBoundingClientRect(),rect=tip.getBoundingClientRect();let shift=0;
  if(rect.left<box.left+4)shift=box.left+4-rect.left;else if(rect.right>box.right-4)shift=box.right-4-rect.right;
  if(shift)tip.style.transform=`translateX(calc(-50% + ${shift}px))`;}
for(const crate of shelves.querySelectorAll('.warehouse-crate')){crate.addEventListener('mouseenter',()=>place(crate));crate.addEventListener('focus',()=>place(crate));}
if(window.ResizeObserver)new ResizeObserver(fit).observe(shelves);fit();})();
