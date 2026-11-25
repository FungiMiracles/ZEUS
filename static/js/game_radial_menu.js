/* 25 Nov 2026: opcje obiektu na mapie obrony i w panelu wojennym wyświetlane w kole dookoła obiektu,
   a opcje regionu — w rzędzie w miejscu kliknięcia (options.layout='row').
   GameRadialMenu.open(map, latlng, items, options) — items: [{label, icon, run, disabled, title, tone}];
   tone — ikona przebarwiona maską: 'attack' czerwona (opcje ataku w panelu wojennym), 'infra' jasnoniebieska (rozbudowa infrastruktury).
   Rząd szerszy niż mapa zawija się w kilka wierszy (telefon).
   Menu zamyka kliknięcie poza obiektem i opcjami, klawisz Esc albo wybór opcji. */
(() => {
    'use strict';
    let current=null;
    const PANE='radialMenu',ITEM_SPACE=104,MIN_RADIUS=72,EDGE=58,ROW_SPACE=102,ROW_HEIGHT=92;
    const reduced=()=>window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    function radiusFor(count){return Math.max(MIN_RADIUS,Math.ceil(count*ITEM_SPACE/(2*Math.PI)));}
    function rowColumns(count,width){return Math.max(1,Math.min(count,Math.floor((width-16)/ROW_SPACE)||1));}
    function rowPoints(count,columns){
        const rows=Math.ceil(count/columns);
        return Array.from({length:count},(_,index)=>{const row=Math.floor(index/columns),inRow=row<rows-1?columns:count-row*columns,column=index%columns;
            return [Math.round((column-(inRow-1)/2)*ROW_SPACE),Math.round((row-(rows-1)/2)*ROW_HEIGHT)];});
    }
    function points(count,radius){
        return Array.from({length:count},(_,index)=>{const angle=-Math.PI/2+2*Math.PI*index/count;return [Math.round(Math.cos(angle)*radius),Math.round(Math.sin(angle)*radius)];});
    }
    function pane(map){
        if(!map.getPane(PANE)){const node=map.createPane(PANE);node.style.zIndex='690';node.style.pointerEvents='none';}
        return PANE;
    }
    // Kliknięcie poza menu zamyka je, chyba że ta sama obsługa kliknięcia otworzyła menu tego samego obiektu (klik w obiekt).
    function outsideClick(event){
        if(!current||current.root.contains(event.target))return;
        const menu=current;menu.keep=false;
        setTimeout(()=>{if(current===menu&&!menu.keep)close();},0);
    }
    function keydown(event){
        if(!current)return;
        if(event.key==='Escape'){event.preventDefault();close({restoreFocus:true});return;}
        if(!current.root.contains(document.activeElement))return;
        const buttons=[...current.root.querySelectorAll('.radial-menu-item')],index=buttons.indexOf(document.activeElement);
        const step={ArrowRight:1,ArrowDown:1,ArrowLeft:-1,ArrowUp:-1}[event.key];
        if(step&&index>=0){event.preventDefault();buttons[(index+step+buttons.length)%buttons.length].focus();}
    }
    function keepInView(map,latlng,extentX,extentY){
        const size=map.getSize(),point=map.latLngToContainerPoint(latlng);
        if(size.x<2*extentX||size.y<2*extentY)return;
        const dx=point.x-extentX<0?point.x-extentX:point.x+extentX>size.x?point.x+extentX-size.x:0;
        const dy=point.y-extentY<0?point.y-extentY:point.y+extentY+14>size.y?point.y+extentY+14-size.y:0;
        if(dx||dy)map.panBy([dx,dy],{animate:!reduced(),duration:.25});
    }
    function open(map,latlng,items,options={}){
        if(!window.L||!map||!latlng)return null;
        const key=options.key||null;
        if(current&&key&&current.key===key&&current.map===map){current.keep=true;if(options.layout==='row')current.marker.setLatLng(latlng);return current;}
        close({immediate:true});
        const usable=(items||[]).filter(item=>item&&item.label);
        if(!usable.length)return null;
        map.closePopup?.();
        const row=options.layout==='row',radius=radiusFor(usable.length),root=document.createElement('div');
        root.className='radial-menu'+(row?' radial-menu-row':'');root.setAttribute('role','group');root.setAttribute('aria-label',options.label||'Opcje obiektu');
        root.style.setProperty('--radius',radius+'px');
        const columns=row?rowColumns(usable.length,map.getSize().x):0,lines=row?Math.ceil(usable.length/columns):0;
        (row?rowPoints(usable.length,columns):points(usable.length,radius)).forEach(([x,y],index)=>{
            const item=usable[index],button=document.createElement('button');
            button.type='button';button.className='radial-menu-item';
            button.style.setProperty('--x',x+'px');button.style.setProperty('--y',y+'px');button.style.setProperty('--i',String(index));
            const icon=document.createElement('span');icon.className='radial-menu-icon';
            if(item.icon&&item.tone){const glyph=document.createElement('span');glyph.className='radial-menu-glyph';glyph.style.setProperty('--glyph',`url("${String(item.icon).replace(/["\\]/g,'\\$&')}")`);icon.append(glyph);button.classList.add('is-'+item.tone);}
            else if(item.icon){const image=document.createElement('img');image.src=item.icon;image.alt='';image.width=26;image.height=26;icon.append(image);}
            const label=document.createElement('span');label.className='radial-menu-label';label.textContent=item.label;
            button.append(icon,label);
            if(item.title)button.title=item.title;
            if(item.disabled){button.setAttribute('aria-disabled','true');button.classList.add('is-disabled');}
            button.addEventListener('click',event=>{
                event.preventDefault();event.stopPropagation();
                if(item.disabled){options.onDisabled?.(item.title||'Ta operacja jest teraz niedostępna.');return;}
                close({immediate:true});item.run?.();
            });
            root.append(button);
        });
        L.DomEvent.disableClickPropagation(root);L.DomEvent.disableScrollPropagation(root);
        const marker=L.marker(latlng,{icon:L.divIcon({html:root,className:'radial-menu-marker',iconSize:[0,0],iconAnchor:[0,0]}),pane:pane(map),interactive:false,keyboard:false}).addTo(map);
        current={key,map,root,marker,keep:true,returnFocus:options.returnFocus||null};
        map.getContainer().classList.add('radial-menu-active');
        document.addEventListener('click',outsideClick,true);
        document.addEventListener('keydown',keydown,true);
        if(reduced())root.classList.add('is-open');
        else requestAnimationFrame(()=>requestAnimationFrame(()=>root.classList.add('is-open')));
        if(row)keepInView(map,latlng,columns*ROW_SPACE/2+8,(lines-1)*ROW_HEIGHT/2+EDGE+10);else keepInView(map,latlng,radius+EDGE,radius+EDGE);
        if(options.focus)root.querySelector('.radial-menu-item:not(.is-disabled)')?.focus({preventScroll:true});
        return current;
    }
    function close(options={}){
        if(!current)return;
        const menu=current;current=null;
        document.removeEventListener('click',outsideClick,true);
        document.removeEventListener('keydown',keydown,true);
        menu.map.getContainer().classList.remove('radial-menu-active');
        if(options.immediate||reduced())menu.marker.remove();
        else{menu.root.classList.remove('is-open');menu.root.classList.add('is-closing');setTimeout(()=>menu.marker.remove(),140);}
        if(options.restoreFocus&&menu.returnFocus?.isConnected)menu.returnFocus.focus({preventScroll:true});
    }
    // Obiekt w ruchu (okręt, armia w marszu): menu przesuwa się razem z nim.
    function follow(key,latlng){if(current&&current.key===key&&latlng)current.marker.setLatLng(latlng);}
    window.GameRadialMenu={open,close,follow,isOpen:()=>!!current,key:()=>current?.key||null,radiusFor};
})();
