/* Shared naval-base / shipyard coastal placement band, clipped to the region. */
(()=>{'use strict';let sequence=0;
function draw({map,layer,segments,widthKm,kmPerUnit,features,regionId}){
    const renderer=L.svg({padding:.5});renderer.addTo(layer);
    const ns='http://www.w3.org/2000/svg',defs=document.createElementNS(ns,'defs'),clip=document.createElementNS(ns,'clipPath'),path=document.createElementNS(ns,'path'),id='game-coast-band-'+(++sequence);
    clip.id=id;clip.setAttribute('clipPathUnits','userSpaceOnUse');path.setAttribute('clip-rule','evenodd');clip.append(path);defs.append(clip);renderer._container.prepend(defs);
    const line=L.polyline(segments.map(segment=>segment.map(p=>L.latLng(p[1],p[0]))),{renderer,color:'#16a34a',opacity:.8,lineCap:'round',lineJoin:'round',interactive:false}).addTo(layer);
    line.getElement().setAttribute('clip-path',`url(#${id})`);line.getElement().classList.add('game-coast-band');
    function update(){let value='';for(const feature of features){if(String(feature.properties?.region_id)!==String(regionId))continue;const polygons=feature.geometry.type==='Polygon'?[feature.geometry.coordinates]:feature.geometry.coordinates;for(const rings of polygons)for(const ring of rings){const points=ring.map(p=>map.latLngToLayerPoint([p[1],p[0]]));value+='M'+points.map(p=>p.x+','+p.y).join('L')+'Z';}}path.setAttribute('d',value);line.setStyle({weight:2*widthKm/kmPerUnit*map.options.crs.scale(map.getZoom())});}
    map.on('zoomend moveend viewreset',update);update();return ()=>{map.off('zoomend moveend viewreset',update);line.remove();renderer.remove();};
}
function allows(segments,x,y,widthKm,kmPerUnit){return segments.some(([a,b])=>{const dx=b[0]-a[0],dy=b[1]-a[1],t=Math.max(0,Math.min(1,((x-a[0])*dx+(y-a[1])*dy)/(dx*dx+dy*dy||1)));return Math.hypot(x-a[0]-t*dx,y-a[1]-t*dy)*kmPerUnit<=widthKm+1e-7;});}
window.GameCoastBand={draw,allows};})();
