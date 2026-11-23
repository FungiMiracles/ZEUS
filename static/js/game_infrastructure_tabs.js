(()=>{'use strict';
// Tabs of the "Infrastruktura i energetyka" page. Previously handled inside road_builder.js; road building was removed
// from the game (10 Nov 2026), so the tabs live here. Same behaviour: remembered tab, ?tab=, arrow/Home/End keys.
const $=id=>document.getElementById(id);
const tabs=['regions','factories','mines','power','communication','air','cities'].filter(tab=>$('infrastructure-tab-'+tab));   // 19 Nov 2026: kolej („Transport kolejowy”); 21 Nov 2026: „Transport lotniczy” i „Miasta”
for(const tab of tabs){
  const button=$('infrastructure-tab-'+tab);if(!button)continue;
  button.addEventListener('click',()=>{
    try{sessionStorage.setItem('infrastructure-tab',tab);}catch{}
    try{button.scrollIntoView({block:'nearest',inline:'nearest'});}catch{}
    for(const name of tabs){const selected=name===tab,item=$('infrastructure-tab-'+name),panel=$('infrastructure-'+name+'-panel');if(!item||!panel)continue;
      item.setAttribute('aria-selected',String(selected));item.tabIndex=selected?0:-1;panel.hidden=!selected;}
  });
  button.addEventListener('keydown',event=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
    event.preventDefault();
    const next=event.key==='Home'?tabs[0]:event.key==='End'?tabs[tabs.length-1]:tabs[(tabs.indexOf(tab)+(event.key==='ArrowLeft'?-1:1)+tabs.length)%tabs.length];
    $('infrastructure-tab-'+next).click();$('infrastructure-tab-'+next).focus();
  });
}
// 23 Nov 2026: zakładki kolei/lotnictwa bez technologii są widoczne, ale wyszarzone — tooltip wyjaśnia, czego brakuje.
// Tooltip jest pływający (position:fixed), bo pasek zakładek na telefonie przewija się poziomo i przycinałby dymek.
const lockedTip=document.createElement('div');lockedTip.className='civic-tab-locked-tip';lockedTip.setAttribute('role','tooltip');lockedTip.hidden=true;document.body.append(lockedTip);
const hideTip=()=>{lockedTip.hidden=true;};
for(const button of document.querySelectorAll('.civic-tab-locked[data-locked-tip]')){
  const show=()=>{lockedTip.textContent=button.dataset.lockedTip;lockedTip.hidden=false;const rect=button.getBoundingClientRect(),box=lockedTip.getBoundingClientRect();
    lockedTip.style.left=Math.max(8,Math.min(rect.left+rect.width/2-box.width/2,window.innerWidth-box.width-8))+'px';
    lockedTip.style.top=(rect.bottom+8+box.height>window.innerHeight?Math.max(8,rect.top-box.height-8):rect.bottom+8)+'px';};
  button.addEventListener('mouseenter',show);button.addEventListener('focus',show);
  button.addEventListener('click',event=>{event.preventDefault();lockedTip.hidden?show():hideTip();});
  button.addEventListener('mouseleave',hideTip);button.addEventListener('blur',hideTip);
}
document.querySelector('.civic-tabs[role=tablist]')?.addEventListener('scroll',hideTip,{passive:true});
window.addEventListener('scroll',hideTip,{passive:true});
let initial=null;
try{initial=new URLSearchParams(location.search).get('tab')||sessionStorage.getItem('infrastructure-tab');}catch{}
if(tabs.includes(initial))$('infrastructure-tab-'+initial)?.click();
})();
