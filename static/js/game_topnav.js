/* 13 Nov 2026: desktopowe menu gry (>900px) — jeden wiersz przewijany poziomo.
   Kółko myszy przewija pasek w poziomie, a aktywna zakładka jest widoczna po wczytaniu strony. */
(()=>{const links=document.getElementById('game-nav-links');if(!links)return;
const desktop=window.matchMedia('(min-width:901px)');
const overflowing=()=>desktop.matches&&links.scrollWidth>links.clientWidth+1;
links.addEventListener('wheel',e=>{if(!overflowing()||e.ctrlKey||Math.abs(e.deltaX)>Math.abs(e.deltaY))return;
  const max=links.scrollWidth-links.clientWidth,next=Math.max(0,Math.min(max,links.scrollLeft+e.deltaY));
  if(next===links.scrollLeft)return;e.preventDefault();links.scrollLeft=next;},{passive:false});
const reveal=()=>{if(!overflowing())return;const active=links.querySelector('[aria-current=page]');if(!active)return;
  const a=active.getBoundingClientRect(),l=links.getBoundingClientRect();
  if(a.left<l.left||a.right>l.right)links.scrollLeft+=a.left-l.left-(l.width-a.width)/2;};
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',reveal);else reveal();
window.addEventListener('load',reveal,{once:true});})();
