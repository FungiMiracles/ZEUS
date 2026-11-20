(()=>{'use strict';
// Tabs of the "Infrastruktura i energetyka" page. Previously handled inside road_builder.js; road building was removed
// from the game (10 Nov 2026), so the tabs live here. Same behaviour: remembered tab, ?tab=, arrow/Home/End keys.
const tabs=['regions','factories','mines','power','communication'];   // 19 Nov 2026: „Komunikacja” (kolej) po opracowaniu technologii
const $=id=>document.getElementById(id);
for(const tab of tabs){
  const button=$('infrastructure-tab-'+tab);if(!button)continue;
  button.addEventListener('click',()=>{
    try{sessionStorage.setItem('infrastructure-tab',tab);}catch{}
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
let initial=null;
try{initial=new URLSearchParams(location.search).get('tab')||sessionStorage.getItem('infrastructure-tab');}catch{}
if(tabs.includes(initial))$('infrastructure-tab-'+initial)?.click();
})();
