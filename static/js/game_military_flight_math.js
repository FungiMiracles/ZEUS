(() => {
    'use strict';
    const clamp=value=>Math.max(0,Math.min(1,value));
    function axis(flight,progress) {
        return [flight.source[1]+(flight.target[1]-flight.source[1])*progress,
                flight.source[0]+(flight.target[0]-flight.source[0])*progress];
    }
    function sample(flight,now) {
        const start=Date.parse(flight.startsAt),impact=Date.parse(flight.impactAt);
        const result={rocket:axis(flight,clamp((now-start)/Math.max(1,impact-start))),rocketVisible:flight.kind!=='air'&&now>=start&&now<impact,jet:null,jetVisible:false,bearing:0};
        if(flight.kind==='air') {
            const arrival=Date.parse(flight.fighterArrivesAt),back=Date.parse(flight.returnsAt),returnStart=Math.max(impact,arrival),returning=now>=returnStart;
            const progress=returning?1-clamp((now-returnStart)/Math.max(1,back-returnStart)):clamp((now-start)/Math.max(1,arrival-start));
            result.jet=axis(flight,progress);result.jetVisible=now>=start&&now<back;
            result.bearing=Math.atan2(-(flight.target[1]-flight.source[1]),flight.target[0]-flight.source[0])*180/Math.PI+90+(returning?180:0);
        }
        return result;
    }
    function gameTime(gameAnchor,realAnchor,now,multiplier) {return gameAnchor+(now-realAnchor)*multiplier;}
    globalThis.MilitaryFlightMath=Object.freeze({sample,gameTime});
})();
