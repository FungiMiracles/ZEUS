/* Rekrutacja i zwolnienia żołnierzy służby czynnej (16 Nov 2026). Rekrutacja bezpłatna; utrzymanie od następnego okresu. */
(() => {
    'use strict';
    const node=document.getElementById('army-recruit-config');if(!node)return;
    const config=JSON.parse(node.textContent),dialog=document.getElementById('army-recruit-dialog'),form=document.getElementById('army-recruit-form');
    const count=document.getElementById('army-recruit-count'),info=document.getElementById('army-recruit-cost'),error=document.getElementById('army-recruit-error');
    const confirm=document.getElementById('army-recruit-confirm');
    const number=value=>new Intl.NumberFormat('pl-PL').format(value).replace(/ /g,' ');
    const money=value=>window.GameMoney?window.GameMoney.format(value):number(Math.round(value))+' ROI';
    let branch=null,action='recruit';
    function room(){
        if(action==='dismiss')return config.branches[branch].reserve;
        return config.limit===null?0:Math.max(0,config.limit-config.total);
    }
    function update(){
        const max=room();
        let value=Math.floor(Number(count.value)||1);value=Math.min(Math.max(1,value),Math.max(1,max));count.value=String(value);count.max=String(Math.max(1,max));
        const data=config.branches[branch],rate=Number(config.rate);
        document.getElementById('army-recruit-current').textContent=action==='recruit'
            ?`${data.label}: ${number(data.total)} w służbie czynnej. Armia łącznie: ${number(config.total)} / ${config.limit===null?'—':number(config.limit)} (limit 30% ludności 18–64).`
            :`${data.label}: w rezerwie ${number(data.reserve)} (zwolnić można tylko żołnierzy nieprzydzielonych do baz).`;
        info.textContent=action==='recruit'
            ?`Rekrutacja bezpłatna. Utrzymanie od następnego okresu: ${money(rate*value)} za okres (${number(rate)} ROI za żołnierza).`
            :`Koszt utrzymania zmniejszy się od następnego okresu o ${money(rate*value)}.`;
        if(action==='recruit'&&config.limit===null)info.textContent='Administrator musi najpierw ustalić strukturę wieku ludności państwa — limit armii jest nieznany.';
        confirm.disabled=max<1;
    }
    document.querySelectorAll('[data-recruit]').forEach(button=>button.addEventListener('click',()=>{
        branch=button.dataset.recruit;action=button.dataset.recruitAction;error.textContent='';
        count.value=String(Math.min(1000,Math.max(1,room())));
        document.getElementById('army-recruit-title').textContent=(action==='recruit'?'Rekrutuj: ':'Zwolnij: ')+config.branches[branch].label;
        confirm.textContent=action==='recruit'?'Rekrutuj':'Zwolnij';
        update();dialog.showModal();
    }));
    const step=()=>Math.max(1,10**Math.max(0,String(Math.floor(Number(count.value)||1)).length-2));
    document.getElementById('army-recruit-minus').onclick=()=>{count.value=String(Math.max(1,(Number(count.value)||1)-step()));update();};
    document.getElementById('army-recruit-plus').onclick=()=>{count.value=String((Number(count.value)||1)+step());update();};
    count.addEventListener('change',update);
    document.getElementById('army-recruit-cancel').onclick=()=>dialog.close();
    form.addEventListener('submit',async event=>{
        event.preventDefault();error.textContent='';confirm.disabled=true;
        try{
            const response=await fetch(config.url,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':config.csrf},
                body:JSON.stringify({action,branch,count:Number(count.value)})});
            const result=await response.json().catch(()=>({}));
            if(!response.ok)throw new Error(result.error||'Nie udało się wykonać operacji.');
            location.reload();
        }catch(exc){error.textContent=exc.message;confirm.disabled=false;}
    });
})();
