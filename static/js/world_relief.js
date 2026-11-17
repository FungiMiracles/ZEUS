/* One continuous illustrated height field for the whole world. Region terrain
   controls elevation and ruggedness, blended across administrative boundaries.
   Land polygons only clip coastlines and lakes; they never clip mountain ranges. */
(() => {
    'use strict';
    const profiles = {
        depresyjny:{height:3,ruggedness:.01}, nizinny:{height:19,ruggedness:.025},
        wyzynny:{height:62,ruggedness:.10}, pogorski:{height:100,ruggedness:.35},
        gorski:{height:165,ruggedness:.75}, wysokogorski:{height:245,ruggedness:1}
    };
    const normalize = name => (name || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/ł/g,'l').trim();
    function hash(x,y) {
        let n=Math.imul(x,374761393)^Math.imul(y,668265263);
        n=Math.imul(n^(n>>>13),1274126177);return(n^(n>>>16))>>>0;
    }
    // Gradient noise produces branching ridgelines, rather than contour bands
    // around interpolated random values at grid vertices.
    function noise(x,y) {
        const ix=Math.floor(x),iy=Math.floor(y),fx=x-ix,fy=y-iy;
        const fade=t=>t*t*t*(t*(t*6-15)+10),sx=fade(fx),sy=fade(fy);
        const gradient=(a,b,dx,dy)=>{
            switch(hash(a,b)&7) {
                case 0:return dx;case 1:return-dx;case 2:return dy;case 3:return-dy;
                case 4:return(dx+dy)*.7071;case 5:return(dx-dy)*.7071;
                case 6:return(-dx+dy)*.7071;default:return(-dx-dy)*.7071;
            }
        };
        const a=gradient(ix,iy,fx,fy),b=gradient(ix+1,iy,fx-1,fy);
        const c=gradient(ix,iy+1,fx,fy-1),d=gradient(ix+1,iy+1,fx-1,fy-1);
        return((a+(b-a)*sx)*(1-sy)+(c+(d-c)*sx)*sy)*1.7;
    }
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
                result.push({rings:coordinates,bounds:[left,top,right,bottom],profile});
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
            ctx.fillStyle=`rgb(${region.profile.height},${Math.round(region.profile.ruggedness*255)},0)`;
            path(ctx,region.rings,left,top,step);
        }
        const pixels=ctx.getImageData(0,0,width,height).data;
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
            let elevation=0,ruggedness=0,weight=0,distance=0;
            for(let dy=0;dy<2;dy++)for(let dx=0;dx<2;dx++) {
                const index=((iy+dy)*width+ix+dx)*3;
                const w=(dx?fx:1-fx)*(dy?fy:1-fy);
                elevation+=data[index]*w;ruggedness+=data[index+1]*w;weight+=data[index+2]*w;
                distance+=coastDistance[(iy+dy)*width+ix+dx]*step*w;
            }
            const t=Math.min(1,Math.max(0,(distance-step*.5)/100)),coast=t*t*(3-2*t);
            return weight?{height:elevation/weight*coast,ruggedness:ruggedness/weight*Math.sqrt(coast),coast,distance}
                :{height:0,ruggedness:0,coast:0,distance:0};
        };
    }
    function elevation(x,y,profile,step=1) {
        const warpX=noise(x/240+9,y/240-12)*55,warpY=noise(x/240-18,y/240+31)*55;
        const u=x*.86+y*.51+warpX,v=-x*.51+y*.86+warpY;
        let ridge=0,amplitude=.57,weight=1,total=0;
        for(let octave=0,scale=125;octave<5;octave++,scale*=.5,amplitude*=.48) {
            if(scale<step*1.5)break;
            let signal=1-Math.abs(noise(u/scale+octave*17.3,v/(scale*.72)-octave*13.7));
            signal=signal*signal*weight;
            ridge+=signal*amplitude;total+=amplitude;weight=Math.min(1,signal*2.2);
        }
        ridge/=total||1;
        const lowland=.94+noise(x/85,y/85)*.06;
        return profile.height*(lowland*(1-profile.ruggedness)+(.16+ridge*1.34)*profile.ruggedness);
    }
    // Muted atlas hypsometry: broad green plains, butter-yellow uplands,
    // ochre foothills and warm brown mountains, with no white/satellite texture.
    const palette = [
        [0,[173,212,143]],[28,[183,218,150]],[38,[222,231,167]],
        [50,[249,237,179]],[85,[246,224,164]],[125,[237,202,148]],
        [175,[225,181,132]],[245,[211,161,117]],[320,[196,146,108]]
    ];
    function atlasColor(height) {
        for(let i=1;i<palette.length;i++)if(height<palette[i][0]) {
            const[a,ca]=palette[i-1],[b,cb]=palette[i],t=Math.max(0,(height-a)/(b-a));
            return ca.map((value,index)=>value+(cb[index]-value)*t);
        }
        return palette[palette.length-1][1];
    }
    function shade(x,y,sample,step) {
        const epsilon=Math.max(1,step*.55),profile=sample(x,y),height=elevation(x,y,profile,step);
        const at=(a,b)=>elevation(a,b,sample(a,b),step);
        const east=at(x+epsilon,y),west=at(x-epsilon,y),south=at(x,y+epsilon),north=at(x,y-epsilon);
        const dx=(east-west)/(2*epsilon),dy=(south-north)/(2*epsilon);
        const light=(.58*dx+.65*dy+.65)/Math.hypot(dx,dy,1);
        const shadow=Math.max(0,Math.min(1,(.65-light)/1.2));
        const curvature=(east+west+south+north-height*4)/(epsilon*epsilon);
        const ridge=Math.max(0,Math.min(1,(-curvature-.025)*3))*profile.ruggedness;
        const darkness=Math.min(.19,shadow*.13+ridge*.06);
        return atlasColor(profile.height*.9+height*.1).map(value=>Math.round(value*(1-darkness)));
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
                    const color=shade(left+(px+.5)*step,top+(py+.5)*step,sample,step);
                    image.data[index]=color[0];image.data[index+1]=color[1];image.data[index+2]=color[2];
                }
                ctx.putImageData(image,0,0);return tile;
            }
        }))({pane:'worldRelief',tileSize:256,minZoom:-10,maxZoom:8,noWrap:true,updateWhenIdle:true,keepBuffer:1,
            attribution:'Ilustracyjna rzeźba terenu wg typów regionów'});
    }
    window.WorldRelief={createLayer,prepare,createModel,elevation,profiles,normalize};
})();
