"""Player-visible event projection shared by human and autonomous state players."""
from flask import Blueprint,jsonify,request
from sqlalchemy import select,or_
from extensions import db
from game.forum import player
from game.autonomy_models import AutonomyEvent
from models import Panstwo

player_context_bp=Blueprint('game_player',__name__,url_prefix='/game/stan')
@player_context_bp.get('/zdarzenia')
def events():
    user,country=player()
    if user is None:return jsonify(error='Zaloguj się ponownie.'),401
    query=select(AutonomyEvent).where(or_(AutonomyEvent.public.is_(True),AutonomyEvent.private_country_id==country.PANSTWO_ID)).order_by(AutonomyEvent.id.desc())
    event_id=request.args.get('event_id',type=int)
    if event_id:query=query.where(AutonomyEvent.id==event_id)
    page=max(1,request.args.get('page',1,type=int) or 1);rows=list(db.session.scalars(query.offset((page-1)*20).limit(21)))
    names=dict(db.session.execute(select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa)).all())
    items=[]
    for event in rows[:20]:
        item={'id':event.id,'kind':event.kind,'game_date':event.occurred_at.isoformat(),'public':event.public}
        if event.public:item.update(actor=names.get(event.actor_id),target=names.get(event.target_id),relation=event.payload.get('relation'),state=event.payload.get('state'))
        elif event.private_country_id==country.PANSTWO_ID:
            item['target']=country.panstwo_nazwa
            if event.kind=='HYBRID_DETECTED':item.update(actor=names.get(event.actor_id),operation=event.payload.get('kind'))
            elif event.kind=='UNATTRIBUTED_DAMAGE':item['actor']='nieustalony'
        items.append(item)
    return jsonify(items=items,next_page=page+1 if len(rows)>20 else None)

@player_context_bp.get('/mapa')
def map_geometry():
    user,country=player()
    if user is None:return jsonify(error='Zaloguj się ponownie.'),401
    from game.military_geography import map_features,MAP_PATH
    from game.governance import controlled_ids
    from shapely.geometry import shape
    from models import Region
    rows=list(db.session.execute(select(Region.region_id,Region.region_nazwa).where(Region.panstwo_id.in_(controlled_ids(db.session,country.PANSTWO_ID))).order_by(Region.region_id)))
    wanted=request.args.get('region_id',type=int)
    if wanted:rows=[row for row in rows if row.region_id==wanted]
    page=max(1,request.args.get('page',1,type=int) or 1);names={row.region_id:row.region_nazwa for row in rows[(page-1)*10:page*10]}
    items=[]
    for feature in map_features(MAP_PATH):
        id=feature.get('properties',{}).get('region_id')
        if id not in names:continue
        geometry=feature['geometry'];point=shape(geometry).representative_point()
        items.append({'region_id':id,'name':names[id],'point':[point.x,point.y],'geometry':geometry})
    return jsonify(items=items,next_page=page+1 if len(rows)>page*10 else None)
