/* Dots in the world view; population-scaled illustrative built-up footprints
   at closer zooms. Source data contains city points, not surveyed urban limits. */
(() => {
    'use strict';
    const NS='http://www.w3.org/2000/svg';let sequence=0;
    function seedFor(value) {
        let seed=2166136261;for(const char of String(value))seed=Math.imul(seed^char.charCodeAt(0),16777619);
        return()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296;};
    }
    function footprint(id,population) {
        const random=seedFor(id),pop=Math.max(0,Number(population)||0);
        const development=Math.min(1,Math.log1p(pop/50000)/Math.log1p(400));
        const radius=3+10*Math.pow(pop/1e6,.43),angle=random()*Math.PI*2,stretch=1+random()*(.25+.55*development);
        const phases=[random()*6.28,random()*6.28,random()*6.28];
        let outline=[];
        for(let i=0;i<48;i++) {
            const a=i/48*Math.PI*2,r=1+(.06+.18*development)*Math.sin(3*a+phases[0])
                +(.025+.12*development)*Math.sin(5*a+phases[1])+.075*development*Math.sin(9*a+phases[2]);
            const x=Math.cos(a)*r*stretch,y=Math.sin(a)*r/stretch;
            outline.push([x*Math.cos(angle)-y*Math.sin(angle),x*Math.sin(angle)+y*Math.cos(angle)]);
        }
        let area=0;outline.forEach(([x,y],i)=>{const next=outline[(i+1)%outline.length];area+=x*next[1]-next[0]*y;});
        const normalization=Math.sqrt(Math.PI/(Math.abs(area)/2));
        outline=outline.map(([x,y])=>[x*normalization,y*normalization]);
        const minX=Math.min(...outline.map(p=>p[0]))-.03,maxX=Math.max(...outline.map(p=>p[0]))+.03;
        const minY=Math.min(...outline.map(p=>p[1]))-.03,maxY=Math.max(...outline.map(p=>p[1]))+.03;
        return {radius,outline,minX,maxX,minY,maxY,area:Math.PI*radius*radius,angle:angle*180/Math.PI,
            cells:Math.max(4,Math.min(16,Math.round(4+Math.log1p(pop/50000)*1.2)))};
    }
    function svgNode(tag,attributes={}) {
        const node=document.createElementNS(NS,tag);for(const[key,value]of Object.entries(attributes))node.setAttribute(key,String(value));return node;
    }
    const ringPath=ring=>ring.map(([x,y],i)=>(i?'L':'M')+x.toFixed(4)+' '+y.toFixed(4)).join('')+'Z';
    function prepareLand(geojson) {
        const result=[];
        for(const feature of geojson?.features||[]) {
            const geometry=feature.geometry,polygons=geometry?.type==='Polygon'?[geometry.coordinates]:geometry?.type==='MultiPolygon'?geometry.coordinates:[];
            for(const rings of polygons)if(rings[0]?.length>=3) {
                const coordinates=rings.filter(ring=>ring.length>=3).map(ring=>ring.map(p=>[p[0],-p[1]]));
                result.push({rings:coordinates,left:Math.min(...coordinates[0].map(p=>p[0])),right:Math.max(...coordinates[0].map(p=>p[0])),
                    top:Math.min(...coordinates[0].map(p=>p[1])),bottom:Math.max(...coordinates[0].map(p=>p[1]))});
            }
        }
        return result;
    }
    function nearbyLand(item,land) {
        const f=item.form,r=f.radius,x=item.latlng.lng,y=-item.latlng.lat;
        return land.filter(p=>p.left<x+f.maxX*r&&p.right>x+f.minX*r&&p.top<y+f.maxY*r&&p.bottom>y+f.minY*r);
    }
    function urbanSVG(item,land) {
        const f=item.form,svg=svgNode('svg',{viewBox:`${f.minX} ${f.minY} ${f.maxX-f.minX} ${f.maxY-f.minY}`,
            class:'world-city-footprint'+(item.city.capital?' is-capital':''),'data-city-id':item.id,'data-urban-area':f.area,role:'button',tabindex:0,'aria-label':item.city.name||'Miasto'});
        const title=svgNode('title');title.textContent=item.city.name||'Miasto';svg.append(title);
        const suffix='urban-'+(++sequence),defs=svgNode('defs'),clip=svgNode('clipPath',{id:suffix});
        clip.append(svgNode('path',{d:ringPath(f.outline)}));defs.append(clip);
        const district=svgNode('g',{'clip-path':`url(#${suffix})`});
        let contents=district;
        if(land.length) {
            const coastId=suffix+'-land',coastClip=svgNode('clipPath',{id:coastId});
            const d=nearbyLand(item,land).map(p=>p.rings.map(ring=>ringPath(ring.map(([x,y])=>[(x-item.latlng.lng)/f.radius,(y+item.latlng.lat)/f.radius]))).join('')).join('');
            coastClip.append(svgNode('path',{d,'clip-rule':'evenodd','fill-rule':'evenodd'}));defs.append(coastClip);
            contents=svgNode('g',{'clip-path':`url(#${coastId})`});district.append(contents);
        }
        const shape=svgNode('path',{d:ringPath(f.outline),fill:'#e6e1d6'});contents.append(shape);
        const blocks=svgNode('g',{transform:`rotate(${f.angle.toFixed(2)})`}),random=seedFor(item.id+'-blocks');
        const extent=2.8,step=extent*2/f.cells;
        for(let row=0;row<f.cells;row++)for(let col=0;col<f.cells;col++) {
            if(random()<.1)continue;
            blocks.append(svgNode('rect',{x:-extent+col*step+step*.09,y:-extent+row*step+step*.09,
                width:step*.82,height:step*.82,fill:random()<.3?'#c1bbae':'#cec7ba'}));
        }
        contents.append(blocks);
        contents.append(svgNode('path',{d:`M${f.minX} .12C-.8 .3 -.1 -.25 ${f.maxX} -.05M.1 ${f.minY}C-.2 -.5 .3 .4 -.1 ${f.maxY}`,
            fill:'none',stroke:'#fffdf5','stroke-width':1,'vector-effect':'non-scaling-stroke'}));
        contents.append(svgNode('path',{d:ringPath(f.outline),class:'urban-outline',fill:'none',stroke:item.city.capital?'#9a7c42':'#8c867b',
            'stroke-width':.8,'vector-effect':'non-scaling-stroke'}));
        svg.append(defs,district);return svg;
    }
    function spatialIndex() {
        const buckets=new Map(),cell=64;
        const keys=box=>{const result=[];for(let x=Math.floor(box[0]/cell);x<=Math.floor(box[2]/cell);x++)for(let y=Math.floor(box[1]/cell);y<=Math.floor(box[3]/cell);y++)result.push(x+':'+y);return result;};
        return {overlaps:box=>keys(box).some(key=>(buckets.get(key)||[]).some(other=>box[0]<other[2]&&box[2]>other[0]&&box[1]<other[3]&&box[3]>other[1])),
            add:box=>{for(const key of keys(box)){if(!buckets.has(key))buckets.set(key,[]);buckets.get(key).push(box);}}};
    }
    function createLayer(L,map,geojson,metadata,options) {
        const cities=[],seen=new Set(),land=prepareLand(options.land);
        for(const feature of geojson.features||[]) {
            const id=String(feature.properties?.miasto_id),city=metadata[id],p=feature.geometry;
            if(!city||seen.has(id)||p?.type!=='Point'||!Array.isArray(p.coordinates)||p.coordinates.length<2||!p.coordinates.slice(0,2).every(Number.isFinite))continue;
            seen.add(id);cities.push({id,city,latlng:L.latLng(p.coordinates[1],p.coordinates[0]),form:footprint(id,city.population)});
        }
        cities.sort((a,b)=>Number(!!b.city.capital)-Number(!!a.city.capital)||(Number(b.city.population)||0)-(Number(a.city.population)||0)||a.id.localeCompare(b.id));
        for(const[name,z]of[['worldCityDots',605],['worldCityLabels',615]])if(!map.getPane(name)){map.createPane(name);map.getPane(name).style.zIndex=String(z);}
        const group=L.layerGroup(),shown=new Map(),measure=document.createElement('canvas').getContext('2d');
        function refresh() {
            if(!map.hasLayer(group))return;
            const zoom=map.getZoom(),scale=Math.pow(2,zoom),viewport=map.getSize(),occupied=spatialIndex(),visible=[];
            for(const item of cities) {
                const point=map.latLngToContainerPoint(item.latlng),f=item.form,pop=Math.max(0,Number(item.city.population)||0);
                const dotRadius=Math.max(item.city.capital?3:1.5,1.5+Math.min(4,Math.log1p(pop/1e5)*.65));
                const detailed=zoom>=-1&&f.radius*scale>=4&&(!land.length||nearbyLand(item,land).length>0);
                const radius=detailed?f.radius*scale:dotRadius;
                const box=detailed?[point.x+f.minX*radius,point.y+f.minY*radius,point.x+f.maxX*radius,point.y+f.maxY*radius]
                    :[point.x-radius-2,point.y-radius-2,point.x+radius+2,point.y+radius+2];
                if(box[2]<0||box[0]>viewport.x||box[3]<0||box[1]>viewport.y)continue;
                if(!detailed&&occupied.overlaps(box))continue;
                occupied.add(box);visible.push({...item,point,box,detailed,dotRadius});
            }
            const ids=new Set(visible.map(item=>item.id));
            for(const[id,record]of shown)if(!ids.has(id)){group.removeLayer(record.body);if(record.label)group.removeLayer(record.label);shown.delete(id);}
            for(const item of visible) {
                let record=shown.get(item.id);
                if(!record||record.detailed!==item.detailed) {
                    if(record){group.removeLayer(record.body);if(record.label)group.removeLayer(record.label);}
                    let body;
                    if(item.detailed) {
                        const f=item.form,r=f.radius;
                        const bounds=L.latLngBounds([item.latlng.lat-f.maxY*r,item.latlng.lng+f.minX*r],[item.latlng.lat-f.minY*r,item.latlng.lng+f.maxX*r]);
                        body=L.svgOverlay(urbanSVG(item,land),bounds,{pane:'worldCities',interactive:true});
                    } else {
                        body=L.circleMarker(item.latlng,{pane:'worldCityDots',radius:item.dotRadius,className:'world-city-dot'+(item.city.capital?' is-capital':''),
                            color:item.city.capital?'#9a7625':'#62646a',weight:item.city.capital?1.4:1,fillColor:item.city.capital?'#efd594':'#fff',fillOpacity:1});
                        body.on('add',()=>{const el=body.getElement();el.dataset.cityId=item.id;el.setAttribute('aria-label',item.city.name||'Miasto');});
                    }
                    body.bindTooltip(options.tooltip(item.city),{direction:'top',className:'world-tooltip'});
                    body.on('click',()=>body.openTooltip());body.addTo(group);
                    record={body,detailed:item.detailed,label:null};shown.set(item.id,record);
                }
                if(record.label){group.removeLayer(record.label);record.label=null;}
                if(zoom<(item.city.capital?-2:((Number(item.city.population)||0)>5e6?-1:0)))continue;
                measure.font=(item.city.capital?'800':'600')+' 12px "Segoe UI",sans-serif';
                const name=(item.city.capital?'★ ':'')+(item.city.name||'Miasto'),width=Math.min(160,Math.ceil(measure.measureText(name).width));
                const x=item.box[2]+4,box=[x,item.point.y-9,x+width+3,item.point.y+9];
                if(box[0]<4||box[1]<4||box[2]>viewport.x-4||box[3]>viewport.y-4||occupied.overlaps(box))continue;
                occupied.add(box);
                const label=document.createElement('span');label.className='world-city-label'+(item.city.capital?' is-capital':'');label.textContent=name;label.style.left=(x-item.point.x)+'px';
                record.label=L.marker(item.latlng,{pane:'worldCityLabels',interactive:false,keyboard:false,
                    icon:L.divIcon({html:label,className:'world-city-name-marker',iconSize:[0,0],iconAnchor:[0,0]})}).addTo(group);
            }
        }
        group.on('add',()=>{map.on('zoomend moveend resize',refresh);refresh();});
        group.on('remove',()=>map.off('zoomend moveend resize',refresh));
        return group;
    }
    window.WorldCityMarkers={createLayer,footprint};
})();
