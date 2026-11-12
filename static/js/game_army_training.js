/* Szkolenie sił zbrojnych (11 Nov 2026): plus/minus, koszt z budżetu sił zbrojnych. */
(() => {
    'use strict';
    const node=document.getElementById('army-training-config');if(!node)return;
    const config=JSON.parse(node.textContent),dialog=document.getElementById('army-training-dialog'),form=document.getElementById('army-training-form');
    const count=document.getElementById('army-training-count'),cost=document.getElementById('army-training-cost'),error=document.getElementById('army-training-error');
    const confirm=document.getElementById('army-training-confirm');
    const money=value=>window.GameMoney?window.GameMoney.format(value):new Intl.NumberFormat('pl-PL').format(Math.round(value))+' ROI';
    let branch=null,requestId=null;
    const uuid=()=>crypto.randomUUID?crypto.randomUUID():'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g,c=>{const r=crypto.getRandomValues(new Uint8Array(1))[0]&15;return (c==='x'?r:(r&3)|8).toString(16);});
    function update(){
        const current=config.levels[branch],room=Math.max(0,config.max-current);
        count.max=String(Math.max(1,room));
        let value=Math.floor(Number(count.value)||1);value=Math.min(Math.max(1,value),Math.max(1,room));count.value=String(value);
        const total=Number(config.prices[branch])*value,available=Number(config.available);
        document.getElementById('army-training-current').textContent=`Obecny poziom: ${current} / ${config.max} → po szkoleniu: ${Math.min(config.max,current+value)} / ${config.max}. Koszt 1 poziomu: ${money(Number(config.prices[branch]))}.`;
        cost.textContent=`Koszt szkolenia: ${money(total)} · dostępne w budżecie sił zbrojnych: ${money(available)}.`;
        cost.classList.toggle('army-training-error',total>available);
        confirm.disabled=room<1||total>available;
        requestId=null;
    }
    document.querySelectorAll('[data-train]').forEach(button=>button.addEventListener('click',()=>{
        branch=button.dataset.train;count.value='1';error.textContent='';
        document.getElementById('army-training-title').textContent='Wyszkol: '+config.labels[branch];
        update();dialog.showModal();
    }));
    document.getElementById('army-training-minus').onclick=()=>{count.value=String(Math.max(1,(Number(count.value)||1)-1));update();};
    document.getElementById('army-training-plus').onclick=()=>{count.value=String((Number(count.value)||1)+1);update();};
    count.addEventListener('input',update);
    document.getElementById('army-training-cancel').onclick=()=>dialog.close();
    form.addEventListener('submit',async event=>{
        event.preventDefault();error.textContent='';confirm.disabled=true;requestId=requestId||uuid();
        try{
            const response=await fetch(config.url,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':config.csrf},
                body:JSON.stringify({branch,levels:Number(count.value),request_id:requestId})});
            const result=await response.json().catch(()=>({}));
            if(!response.ok)throw new Error(result.error||'Nie udało się przeprowadzić szkolenia.');
            location.reload();
        }catch(exc){error.textContent=exc.message;confirm.disabled=false;}
    });
})();
