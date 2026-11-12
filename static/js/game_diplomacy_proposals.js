"use strict";
(() => {
    for(const form of document.querySelectorAll('[data-diplomacy-proposal-form]')){
        form.addEventListener('submit',async event=>{
            event.preventDefault();
            if(form.dataset.busy)return;
            const decision=event.submitter?.value;
            if(!['accept','reject'].includes(decision))return;
            form.dataset.busy='1';
            const buttons=form.querySelectorAll('button'),status=form.querySelector('[data-proposal-result]');
            buttons.forEach(button=>button.disabled=true);status.hidden=false;status.textContent='Zapisywanie…';
            const body=new FormData(form);body.set('decision',decision);
            try{
                const response=await fetch(form.action,{method:'POST',credentials:'same-origin',headers:{Accept:'application/json'},body});
                const data=await response.json();
                if(!response.ok){if(response.status===409)form.dataset.stale='1';throw new Error(data.error||'Nie udało się zapisać odpowiedzi.');}
                window.location.reload();
            }catch(error){status.textContent=error.message;}
            finally{delete form.dataset.busy;if(!form.dataset.stale)buttons.forEach(button=>button.disabled=false);}
        });
    }
})();
