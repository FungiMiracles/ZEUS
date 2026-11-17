/* Zoom-aware city pins and collision-free place labels. Only visible markers
   are mounted; city metadata/names always remain text, never HTML. */
(() => {
    'use strict';
    function createLayer(L,map,geojson,metadata,options) {
        const cities=[],seen=new Set();
        for(const feature of geojson.features||[]) {
            const id=String(feature.properties?.miasto_id),city=metadata[id],point=feature.geometry;
            if(!city||seen.has(id)||point?.type!=='Point'||!Array.isArray(point.coordinates)||point.coordinates.length<2||!point.coordinates.slice(0,2).every(Number.isFinite))continue;
            seen.add(id);
            cities.push({id,city,latlng:L.latLng(point.coordinates[1],point.coordinates[0])});
        }
        cities.sort((a,b)=>Number(!!b.city.capital)-Number(!!a.city.capital)||(Number(b.city.population)||0)-(Number(a.city.population)||0)||a.id.localeCompare(b.id));
        const group=L.layerGroup(),shown=new Map(),measure=document.createElement('canvas').getContext('2d');
        function spatialIndex() {
            const buckets=new Map(),cell=64;
            const keys=box=>{
                const result=[];
                for(let x=Math.floor(box[0]/cell);x<=Math.floor(box[2]/cell);x++)for(let y=Math.floor(box[1]/cell);y<=Math.floor(box[3]/cell);y++)result.push(x+':'+y);
                return result;
            };
            return {
                overlaps:box=>keys(box).some(key=>(buckets.get(key)||[]).some(other=>box[0]<other[2]&&box[2]>other[0]&&box[1]<other[3]&&box[3]>other[1])),
                add:box=>{for(const key of keys(box)){if(!buckets.has(key))buckets.set(key,[]);buckets.get(key).push(box);}}
            };
        }
        function refresh() {
            if(!map.hasLayer(group))return;
            const zoom=map.getZoom(),viewport=map.getSize(),occupied=spatialIndex(),visible=[];
            for(const item of cities) {
                const population=Number(item.city.population)||0;
                if(!item.city.capital&&(zoom<-2&&population<=5e6||zoom<-1&&population<1e6))continue;
                const point=map.latLngToContainerPoint(item.latlng);
                if(point.x<-40||point.x>viewport.x+40||point.y<-40||point.y>viewport.y+40)continue;
                const base=item.city.capital?30:population>5e6?28:population>=1e6?24:20;
                const size=Math.round(base*(zoom<-2?.66:zoom<-1?.82:1)),gap=zoom<-1?7:3;
                const box=[point.x-size/2-gap,point.y-size-gap,point.x+size/2+gap,point.y+gap];
                if(occupied.overlaps(box))continue;
                occupied.add(box);visible.push({...item,point,size});
            }
            const ids=new Set(visible.map(item=>item.id));
            for(const[id,record]of shown)if(!ids.has(id)){group.removeLayer(record.marker);shown.delete(id);}
            for(const item of visible) {
                let record=shown.get(item.id);
                if(!record||record.size!==item.size) {
                    if(record)group.removeLayer(record.marker);
                    const symbol=document.createElement('span');symbol.className='world-city-place'+(item.city.capital?' is-capital':'');
                    const image=document.createElement('img');image.src=item.city.capital?options.capitalIcon:options.cityIcon;image.alt='';image.draggable=false;
                    const label=document.createElement('span');label.className='world-city-label';label.textContent=item.city.name||'Miasto';
                    symbol.append(image,label);
                    const marker=L.marker(item.latlng,{pane:'worldCities',title:(item.city.name||'Miasto')+(item.city.capital?' — stolica':''),
                        icon:L.divIcon({html:symbol,className:'world-city-marker',iconSize:[item.size,item.size],iconAnchor:[item.size/2,item.size]}),
                        zIndexOffset:item.city.capital?500:0});
                    marker.bindTooltip(options.tooltip(item.city),{direction:'top',offset:L.point(0,-item.size),className:'world-tooltip'});
                    marker.on('click',()=>marker.openTooltip());marker.addTo(group);
                    record={marker,symbol,label,size:item.size};shown.set(item.id,record);
                }
                record.symbol.classList.remove('has-label');
                if(zoom<(item.city.capital?-2:((Number(item.city.population)||0)>5e6?-1:0)))continue;
                measure.font=(item.city.capital?'800':'600')+' 12px "Segoe UI",sans-serif';
                const width=Math.min(160,Math.ceil(measure.measureText(item.city.name||'Miasto').width));
                const box=[item.point.x+item.size/2+3,item.point.y-item.size/2-9,item.point.x+item.size/2+7+width,item.point.y-item.size/2+9];
                if(box[0]<4||box[1]<4||box[2]>viewport.x-4||box[3]>viewport.y-4||occupied.overlaps(box))continue;
                occupied.add(box);record.symbol.classList.add('has-label');
            }
        }
        group.on('add',()=>{map.on('zoomend moveend resize',refresh);refresh();});
        group.on('remove',()=>map.off('zoomend moveend resize',refresh));
        return group;
    }
    window.WorldCityMarkers={createLayer};
})();
