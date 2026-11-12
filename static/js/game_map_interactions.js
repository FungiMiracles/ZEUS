(() => {
    'use strict';
    window.GameHealth={paint(bar,value){const health=Math.max(0,Math.min(100,Number(value)||0));bar.dataset.health=health<=25?'low':health<75?'damaged':'healthy';bar.classList.add('health-progress');bar.setAttribute('aria-label',`Życie: ${health}%`);}};
    const isMap=target=>target instanceof Element&&target.closest('.leaflet-container');
    for(const type of ['touchstart','touchmove'])document.addEventListener(type,event=>{if(event.touches.length>1&&isMap(event.target)&&event.cancelable)event.preventDefault();},{passive:false,capture:true});
    for(const type of ['gesturestart','gesturechange'])document.addEventListener(type,event=>{if(isMap(event.target)&&event.cancelable)event.preventDefault();},{passive:false,capture:true});
})();
