/* Flat 2D atlas hypsometry. Regional elevation bands blend across borders,
   taper at coastlines and contain no lighting, shading or surface texture. */
(() => {
    'use strict';
    const profiles = {
        depresyjny:{height:3,ruggedness:.01}, nizinny:{height:19,ruggedness:.025},
        wyzynny:{height:62,ruggedness:.10}, pogorski:{height:100,ruggedness:.35},
        gorski:{height:165,ruggedness:.75}, wysokogorski:{height:245,ruggedness:1}
    };
    const normalize = name => (name || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/ł/g,'l').trim();
    function prepare(geojson,metadata) {
        const result=[];
        for(const feature of geojson.features||[]) {
            const profile=profiles[normalize(metadata[String(feature.properties?.region_id)]?.terrain)]||profiles.nizinny;
            const geometry=feature.geometry;
            const polygons=geometry?.type==='Polygon'?[geometry.coordinates]:geometry?.type==='MultiPolygon'?geometry.coordinates:[];
            for(const rings of polygons) {
                const coordinates=rings.filter(ring=>ring.length>=3).map(ring=>ring.map(p=>[p[0],-p[1]]));
                if(!coordinates.length)continue;
                let left=Infinity,top=Infinity,right=-Infinity,bottom=-Infinity;
                for(const[x,y]of coordinates[0]){left=Math.min(left,x);right=Math.max(right,x);top=Math.min(top,y);bottom=Math.max(bottom,y);}
                result.push({rings:coordinates,bounds:[left,top,right,bottom],profile,kao:normalize(metadata[String(feature.properties?.region_id)]?.continent)==='kao'});
            }
        }
        return result;
    }
    function path(ctx,rings,left,top,step) {
        ctx.beginPath();
        for(const ring of rings) {
            ring.forEach(([x,y],i)=>{const px=(x-left)/step,py=(y-top)/step;if(i)ctx.lineTo(px,py);else ctx.moveTo(px,py);});
            ctx.closePath();
        }
        ctx.fill('evenodd');
    }
    function createModel(terrain) {
        if(!terrain.length)return()=>profiles.nizinny;
        const left=Math.min(...terrain.map(r=>r.bounds[0]))-100,top=Math.min(...terrain.map(r=>r.bounds[1]))-100;
        const right=Math.max(...terrain.map(r=>r.bounds[2]))+100,bottom=Math.max(...terrain.map(r=>r.bounds[3]))+100;
        const step=Math.max(2,(right-left)/1600,(bottom-top)/1600);
        const width=Math.ceil((right-left)/step),height=Math.ceil((bottom-top)/step);
        const source=document.createElement('canvas');source.width=width;source.height=height;
        const ctx=source.getContext('2d');
        for(const region of terrain) {
            ctx.fillStyle=`rgb(${region.profile.height},${Math.round(region.profile.ruggedness*255)},${region.kao?255:0})`;
            path(ctx,region.rings,left,top,step);
        }
        const pixels=ctx.getImageData(0,0,width,height).data;
        // Locate Kao's mainland from connected land, so overseas possessions
        // do not change the western continental coast adjustment.
        const components=new Uint32Array(width*height);
        let kao={id:0,count:0,left:0,right:1};
        if(terrain.some(region=>region.kao)) {
            const queue=new Uint32Array(width*height);let id=0,tail=0;
            const enqueue=i=>{if(!components[i]&&pixels[i*4+3]>127){components[i]=id;queue[tail++]=i;}};
            for(let start=0;start<components.length;start++) {
                if(components[start]||pixels[start*4+3]<=127)continue;
                id++;tail=0;enqueue(start);let head=0,count=0,minX=width,maxX=0;
                while(head<tail) {
                    const i=queue[head++],x=i%width,y=Math.floor(i/width);
                    if(pixels[i*4+2]>127)count++;
                    minX=Math.min(minX,x);maxX=Math.max(maxX,x);
                    if(x>0)enqueue(i-1);if(x<width-1)enqueue(i+1);
                    if(y>0)enqueue(i-width);if(y<height-1)enqueue(i+width);
                }
                if(count>kao.count)kao={id,count,left:left+minX*step,right:left+(maxX+1)*step};
            }
        }
        // Distance from the union of land, never from regional borders. Both
        // raster passes propagate shoreline distances across the whole continent.
        const coastDistance=new Float32Array(width*height),diagonal=Math.SQRT2;
        for(let i=0;i<coastDistance.length;i++)coastDistance[i]=pixels[i*4+3]>127?1e6:0;
        for(let y=1;y<height-1;y++)for(let x=1;x<width-1;x++) {
            const i=y*width+x;
            coastDistance[i]=Math.min(coastDistance[i],coastDistance[i-1]+1,coastDistance[i-width]+1,
                coastDistance[i-width-1]+diagonal,coastDistance[i-width+1]+diagonal);
        }
        for(let y=height-2;y>0;y--)for(let x=width-2;x>0;x--) {
            const i=y*width+x;
            coastDistance[i]=Math.min(coastDistance[i],coastDistance[i+1]+1,coastDistance[i+width]+1,
                coastDistance[i+width+1]+diagonal,coastDistance[i+width-1]+diagonal);
        }
        let data=new Float32Array(width*height*3),scratch=new Float32Array(data.length);
        for(let i=0;i<width*height;i++) {
            const alpha=pixels[i*4+3]/255;
            data[i*3]=pixels[i*4]*alpha;data[i*3+1]=pixels[i*4+1]/255*alpha;data[i*3+2]=alpha;
        }
        // Blur floating-point parameters, not RGB colors: 8-bit blur creates
        // artificial contour steps, especially on otherwise flat lowlands.
        const radius=Math.max(1,Math.round(30/step)),diameter=radius*2+1;
        function blur(horizontal) {
            const lines=horizontal?height:width,length=horizontal?width:height,stride=horizontal?3:width*3;
            for(let line=0;line<lines;line++) {
                const base=horizontal?line*width*3:line*3;
                let h=0,r=0,w=0;
                for(let k=-radius;k<=radius;k++) {
                    const j=base+Math.max(0,Math.min(length-1,k))*stride;
                    h+=data[j];r+=data[j+1];w+=data[j+2];
                }
                for(let i=0;i<length;i++) {
                    const j=base+i*stride;scratch[j]=h/diameter;scratch[j+1]=r/diameter;scratch[j+2]=w/diameter;
                    const before=base+Math.max(0,i-radius)*stride,after=base+Math.min(length-1,i+radius+1)*stride;
                    h+=data[after]-data[before];r+=data[after+1]-data[before+1];w+=data[after+2]-data[before+2];
                }
            }
            [data,scratch]=[scratch,data];
        }
        for(let pass=0;pass<3;pass++){blur(true);blur(false);}
        return(x,y)=>{
            const px=Math.max(0,Math.min(width-1.001,(x-left)/step-.5)),py=Math.max(0,Math.min(height-1.001,(y-top)/step-.5));
            const ix=Math.floor(px),iy=Math.floor(py),fx=px-ix,fy=py-iy;
            let elevation=0,ruggedness=0,weight=0,distance=0,kaoWeight=0;
            for(let dy=0;dy<2;dy++)for(let dx=0;dx<2;dx++) {
                const index=((iy+dy)*width+ix+dx)*3;
                const w=(dx?fx:1-fx)*(dy?fy:1-fy);
                elevation+=data[index]*w;ruggedness+=data[index+1]*w;weight+=data[index+2]*w;
                distance+=coastDistance[(iy+dy)*width+ix+dx]*step*w;
                if(kao.id&&components[(iy+dy)*width+ix+dx]===kao.id)kaoWeight+=w;
            }
            const across=(x-kao.left)/(kao.right-kao.left),blend=Math.max(0,Math.min(1,(across-.3)/.3));
            const west=1-blend*blend*(3-2*blend),coastSpan=100-35*kaoWeight*west;
            const t=Math.min(1,Math.max(0,(distance-step*.5)/coastSpan)),coast=t*t*(3-2*t);
            return weight?{height:elevation/weight*coast,ruggedness:ruggedness/weight*Math.sqrt(coast),coast,distance,coastSpan}
                :{height:0,ruggedness:0,coast:0,distance:0};
        };
    }
    // Flat atlas bands, not gradients: no directional illumination, grain,
    // highlights or shaded slopes that could suggest a 3D surface.
    const palette = [
        [30,[183,218,150]],[65,[249,237,179]],[115,[246,224,164]],
        [155,[237,202,148]],[210,[225,181,132]],[Infinity,[211,161,117]]
    ];
    function atlasColor(height) {
        return palette.find(([limit])=>height<limit)[1];
    }
    function createLayer(L,geojson,metadata) {
        const terrain=prepare(geojson,metadata),sample=createModel(terrain);
        return new(L.GridLayer.extend({
            createTile(coords) {
                const size=192,tile=document.createElement('canvas');tile.width=size;tile.height=size;
                const ctx=tile.getContext('2d'),scale=Math.pow(2,coords.z),step=256/size/scale;
                const left=coords.x*256/scale,top=coords.y*256/scale,right=left+256/scale,bottom=top+256/scale;
                const visible=terrain.filter(r=>r.bounds[0]<right&&r.bounds[2]>left&&r.bounds[1]<bottom&&r.bounds[3]>top);
                if(!visible.length)return tile;
                ctx.fillStyle='#fff';for(const region of visible)path(ctx,region.rings,left,top,step);
                const image=ctx.getImageData(0,0,size,size);
                for(let py=0;py<size;py++)for(let px=0;px<size;px++) {
                    const index=(py*size+px)*4;if(!image.data[index+3])continue;
                    const color=atlasColor(sample(left+(px+.5)*step,top+(py+.5)*step).height).map(Math.round);
                    image.data[index]=color[0];image.data[index+1]=color[1];image.data[index+2]=color[2];
                }
                ctx.putImageData(image,0,0);return tile;
            }
        }))({pane:'worldRelief',tileSize:256,minZoom:-10,maxZoom:8,noWrap:true,updateWhenIdle:true,keepBuffer:1,
            attribution:'Ilustracyjna rzeźba terenu wg typów regionów'});
    }
    window.WorldRelief={createLayer,prepare,createModel,atlasColor,profiles,normalize};
})();
