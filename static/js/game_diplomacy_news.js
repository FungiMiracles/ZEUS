"use strict";
(() => {
    const root=document.getElementById('diplomacy-world-news');
    if(!root)return;
    const list=root.querySelector('[data-news-list]'),status=root.querySelector('[data-news-status]'),badge=root.querySelector('[data-news-count]'),more=root.querySelector('[data-news-more]'),toggle=root.querySelector('summary');
    const dropdown=root.querySelector('.game-notification-dropdown');
    function positionDropdown(){
        if(!root.open)return;
        const rect=toggle.getBoundingClientRect(),margin=12,gap=10;
        const width=Math.min(380,window.innerWidth-2*margin);
        const left=Math.max(margin,Math.min(rect.right-width,window.innerWidth-width-margin));
        const below=window.innerHeight-rect.bottom-gap-margin,above=rect.top-gap-margin;
        const up=below<160&&above>below;
        const height=Math.max(80,Math.min(window.innerHeight*.65,up?above:below));
        dropdown.style.setProperty('--news-left',`${left}px`);
        dropdown.style.setProperty('--news-height',`${height}px`);
        const top=up?rect.top-gap-dropdown.getBoundingClientRect().height:rect.bottom+gap;
        dropdown.style.setProperty('--news-top',`${Math.max(margin,top)}px`);
    }
    window.addEventListener('resize',positionDropdown);
    window.addEventListener('scroll',positionDropdown,true);
    let busy=false,next=null;
    const shown=new Set();
    const readAll=root.querySelector('[data-news-read-all]');
    function count(value){badge.textContent=String(value);badge.hidden=value===0;if(readAll)readAll.hidden=value===0;toggle.setAttribute('aria-label',`Powiadomienia dyplomatyczne ze świata: ${value} nieprzeczytanych`);}
    // 16 Nov 2026: „Oznacz wszystkie jako przeczytane” — także powiadomienia na niewczytanych jeszcze stronach listy.
    if(readAll)readAll.addEventListener('click',async()=>{
        readAll.disabled=true;
        try{
            const body=new FormData();body.set('csrf_token',root.dataset.csrf);body.set('all','1');
            const response=await fetch(root.dataset.readUrl,{method:'POST',credentials:'same-origin',body});
            if(!response.ok)throw new Error();
            count((await response.json()).unread_count);
            list.querySelectorAll('.unread').forEach(item=>item.classList.remove('unread'));
        }catch(error){status.hidden=false;status.textContent='Nie udało się oznaczyć powiadomień.';}
        finally{readAll.disabled=false;}
    });
    async function load(page=1,countOnly=false){
        if(busy)return;
        busy=true;more.disabled=true;
        try{
            const url=new URL(root.dataset.url,location.origin);url.searchParams.set('page',String(page));
            const response=await fetch(url,{credentials:'same-origin',cache:'no-store'});
            if(!response.ok)throw new Error();
            const data=await response.json();count(data.unread_count);
            if(countOnly)return;
            if(page===1){list.replaceChildren();shown.clear();}
            for(const item of data.items){
                if(shown.has(item.id))continue;
                shown.add(item.id);
                const card=document.createElement('article');card.className='game-notification-item'+(item.unread?' unread':'')+(item.severity==='war'?' notification-war':'');
                const flags=document.createElement('div');flags.className='diplomacy-news-flags';
                item.flags.forEach((flag,index)=>{if(index)flags.append(document.createTextNode(' — '));const img=document.createElement('img');img.src=flag.url;img.alt=flag.name;img.width=36;img.height=24;flags.append(img);});
                const text=document.createElement('p');text.textContent=item.text;
                const date=document.createElement('small');date.textContent=item.gameAt.replace('T',' ')+' (Entenda)';
                card.append(flags,text,date);list.append(card);
            }
            next=data.next_page;more.hidden=!next;status.hidden=shown.size>0;status.textContent='Brak powiadomień.';
            if(root.open){
                const unread=data.items.filter(item=>item.unread);
                if(unread.length){
                    const body=new FormData();body.set('csrf_token',root.dataset.csrf);unread.forEach(item=>body.append('ids',String(item.id)));
                    const read=await fetch(root.dataset.readUrl,{method:'POST',credentials:'same-origin',body});
                    if(!read.ok)throw new Error();count((await read.json()).unread_count);
                    list.querySelectorAll('.unread').forEach(item=>item.classList.remove('unread'));
                }
            }
        }catch(error){status.hidden=false;status.textContent='Nie udało się pobrać powiadomień. Otwórz listę ponownie.';}
        finally{busy=false;more.disabled=false;positionDropdown();}
    }
    root.addEventListener('toggle',()=>{if(root.open){positionDropdown();load();}});
    root.addEventListener('keydown',event=>{if(event.key==='Escape'){root.open=false;toggle.focus();}});
    document.addEventListener('click',event=>{if(root.open&&!root.contains(event.target))root.open=false;});
    more.addEventListener('click',()=>{if(next)load(next);});
    load(1,true);
    setInterval(()=>{if(!document.hidden)load(1,!root.open);},30000);
})();
