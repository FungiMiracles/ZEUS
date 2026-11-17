/* Illustrated elevation, not measured altitudes. Stable world-space ridgelines,
   clipped to region polygons (including holes), shaded from the north-west.
   Canvas tiles keep work bounded to the visible area at every zoom. */
(() => {
    'use strict';
    const profiles = {
        wysokogorski: {height:165, sharpness:3.4, detail:1, snow:true},
        gorski: {height:90, sharpness:2.7, detail:.8},
        pogorski: {height:32, sharpness:1.6, detail:.4},
        wyzynny: {height:13, sharpness:.7, detail:.12}
    };
    const normalize = name => (name || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/ł/g,'l').trim();
    function hash(x, y) {
        let value = Math.imul(x, 374761393) ^ Math.imul(y, 668265263);
        value = Math.imul(value ^ (value >>> 13), 1274126177);
        return ((value ^ (value >>> 16)) >>> 0) / 4294967295;
    }
    function noise(x, y) {
        const ix = Math.floor(x), iy = Math.floor(y), fx = x - ix, fy = y - iy;
        const sx = fx * fx * (3 - 2 * fx), sy = fy * fy * (3 - 2 * fy);
        const a = hash(ix,iy), b = hash(ix+1,iy), c = hash(ix,iy+1), d = hash(ix+1,iy+1);
        return (a + (b-a)*sx) * (1-sy) + (c + (d-c)*sx) * sy;
    }
    function elevation(x, y, profile) {
        const warp = (noise(x/210+13,y/210-7)-.5)*90;
        const u = x*.87 + y*.49 + warp, v = -x*.49 + y*.87 + warp*.45;
        const ridge = (scale, offset) => Math.pow(1-Math.abs(noise(u/scale+offset,v/(scale*.57)+offset)*2-1),profile.sharpness);
        return profile.height * (ridge(115,0)*.72 + ridge(48,41)*.2*profile.detail + ridge(19,87)*.08*profile.detail);
    }
    function prepare(geojson, metadata) {
        const result = [];
        for (const feature of geojson.features || []) {
            const profile = profiles[normalize(metadata[String(feature.properties?.region_id)]?.terrain)];
            if (!profile) continue;
            const geometry = feature.geometry;
            const polygons = geometry?.type === 'Polygon' ? [geometry.coordinates] : geometry?.type === 'MultiPolygon' ? geometry.coordinates : [];
            for (const rings of polygons) {
                if (!rings[0]?.length) continue;
                const coordinates = rings.filter(ring=>ring.length>=3).map(ring=>ring.map(point=>[point[0],-point[1]]));
                if (!coordinates.length) continue;
                let left=Infinity,top=Infinity,right=-Infinity,bottom=-Infinity;
                for (const [x,y] of coordinates[0]) {left=Math.min(left,x);right=Math.max(right,x);top=Math.min(top,y);bottom=Math.max(bottom,y);}
                result.push({rings:coordinates,bounds:[left,top,right,bottom],profile});
            }
        }
        return result;
    }
    function shade(x, y, profile, step) {
        const height = elevation(x,y,profile), epsilon = Math.max(1,step*.5);
        const dx = (elevation(x+epsilon,y,profile)-height)/epsilon;
        const dy = (elevation(x,y+epsilon,profile)-height)/epsilon;
        const light = Math.max(.32,Math.min(1.25,.68+(.55*dx+.65*dy+.6)/Math.hypot(dx,dy,1)*.65));
        const rock = Math.max(0,Math.min(1,(height/profile.height-.28)*1.6));
        let color = [176-rock*25,188-rock*48,151-rock*40];
        if (profile.snow && height/profile.height>.64) {
            const snow = Math.min(1,(height/profile.height-.64)*12);
            color=color.map((value,index)=>value+( [240,244,242][index]-value)*snow);
        }
        return color.map(value=>Math.max(0,Math.min(255,Math.round(value*light))));
    }
    function createLayer(L, geojson, metadata) {
        const terrain = prepare(geojson,metadata);
        return new (L.GridLayer.extend({
            createTile(coords) {
                // 128 samples per tile, smoothly upscaled by Leaflet to 256 CSS pixels.
                const size=128, tile=document.createElement('canvas');tile.width=size;tile.height=size;
                const ctx=tile.getContext('2d'),scale=Math.pow(2,coords.z),step=2/scale;
                const left=coords.x*256/scale,top=coords.y*256/scale,right=left+256/scale,bottom=top+256/scale;
                const visible=terrain.filter(item=>item.bounds[0]<right&&item.bounds[2]>left&&item.bounds[1]<bottom&&item.bounds[3]>top);
                if (!visible.length) return tile;
                const mask=document.createElement('canvas');mask.width=size;mask.height=size;
                const maskCtx=mask.getContext('2d');
                for (const profile of Object.values(profiles)) {
                    const polygons=visible.filter(item=>item.profile===profile);if(!polygons.length)continue;
                    maskCtx.clearRect(0,0,size,size);maskCtx.fillStyle='#fff';
                    for (const item of polygons) {
                        maskCtx.beginPath();
                        for (const ring of item.rings) {
                            ring.forEach(([x,y],index)=>{const px=(x-left)/step,py=(y-top)/step;if(index)maskCtx.lineTo(px,py);else maskCtx.moveTo(px,py);});
                            maskCtx.closePath();
                        }
                        maskCtx.fill('evenodd');
                    }
                    const alpha=maskCtx.getImageData(0,0,size,size).data,image=ctx.createImageData(size,size);
                    for(let py=0;py<size;py++)for(let px=0;px<size;px++) {
                        const index=(py*size+px)*4;if(!alpha[index+3])continue;
                        const color=shade(left+(px+.5)*step,top+(py+.5)*step,profile,step);
                        image.data[index]=color[0];image.data[index+1]=color[1];image.data[index+2]=color[2];image.data[index+3]=alpha[index+3]*.92;
                    }
                    // Composite types instead of replacing previous terrain in this tile.
                    maskCtx.putImageData(image,0,0);ctx.drawImage(mask,0,0);
                }
                return tile;
            }
        }))({pane:'worldRelief',tileSize:256,minZoom:-10,maxZoom:8,noWrap:true,updateWhenIdle:true,keepBuffer:1,
            attribution:'Ilustracyjna rzeźba terenu wg typów regionów'});
    }
    window.WorldRelief={createLayer,prepare,elevation,profiles,normalize};
})();
