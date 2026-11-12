"""Decision data and decision grammar for military, diplomatic and messaging actions of PAGA AI.

UAT 10 Nov 2026 (tasks 359–361): the model invented base/defense/region numbers and wrote country ids where user ids
were needed, because (a) the military page data covering the whole world was cut to a useless summary and (b) the grammar
accepted any field of any type. Here the player-route data is projected to the facts needed for a decision, and each
action gets its own exact shape. No strategy is chosen: the model still decides what, where and against whom.
"""
from decimal import Decimal

LIMIT=18
INFRASTRUCTURE=['road','rail','energy','housing','port','connection']
MISSILES=['short','medium','long']
BASE_KINDS=['land','air','naval','nuclear']
TARGET_FIELDS=['city_id','target_base_id','target_vessel_id','target_factory_id','target_power_id','target_mine_id','target_defense_id','target_shipment_id']


def _config(result):
    """military_config embedded in the player's military pages (PlayerDocument puts JSON scripts into game_data)."""
    if not isinstance(result,dict):return None
    for item in result.get('game_data') or []:
        if isinstance(item,dict) and 'regions' in item and 'missiles' in item:return item
    return None


def military_view(result):
    config=_config(result)
    if config is None:return result if not isinstance(result,dict) else {key:result[key] for key in ('error','visible_text') if key in result}
    own=config.get('countryId');controlled=set(config.get('controlledCountryIds') or [own]);enemies=set(config.get('enemyIds') or [])
    countries={int(key):value for key,value in (config.get('countries') or {}).items() if str(key).isdigit()}
    regions=config.get('regions') or {};cities=config.get('cities') or {}
    own_regions=[{'region_id':int(key),'nazwa':value.get('name'),'nadmorski':value.get('coastal')} for key,value in regions.items() if value.get('countryId') in controlled]
    enemy_regions=[{'region_id':int(key),'nazwa':value.get('name'),'państwo':countries.get(value.get('countryId'))} for key,value in regions.items() if value.get('countryId') in enemies]
    enemy_cities=[{'city_id':int(key),'nazwa':value.get('name'),'region_id':int(value['regionId']) if str(value.get('regionId','')).isdigit() else None} for key,value in cities.items() if value.get('countryId') in enemies]
    bases=[{'base_id':base.get('id'),'rodzaj':base.get('kind'),'region_id':base.get('regionId'),'nazwa':base.get('name'),'poziom':base.get('level'),
            'garnizon':base.get('garrison'),'sprawna':base.get('operational'),'zdrowie':base.get('health')}
           for base in config.get('bases') or [] if base.get('countryId') in controlled]
    known=[{'base_id':base.get('id'),'rodzaj':base.get('kind'),'region_id':base.get('regionId'),'państwo':countries.get(base.get('countryId'))}
           for base in config.get('visibleBases') or [] if base.get('countryId') not in controlled]
    defenses=[{'defense_id':item.get('id'),'chroni':f"{item.get('targetKind') or item.get('target_kind')} #{item.get('targetId') or item.get('target_id')}",
               'poziom':item.get('level'),'amunicja':item.get('ammunition'),'zdrowie':item.get('health')}
              for item in config.get('defenses') or [] if (item.get('countryId') or item.get('panstwo_id') or own) in controlled]
    land_targets=[{'region_id':value,'nazwa':(regions.get(str(value)) or {}).get('name'),'państwo':countries.get((regions.get(str(value)) or {}).get('countryId'))} for value in config.get('landTargets') or []]
    view={'nasze_państwo_id':own,'w_wojnie_z':[{'country_id':id,'nazwa':countries.get(id)} for id in sorted(enemies)],
          'rakiety':{code:(value or {}).get('count') for code,value in (config.get('missiles') or {}).items()},
          'wojska_lądowe':config.get('groundInventory'),'mamy_okręty_wojenne':config.get('hasWarships'),
          'nasze_bazy':bases[:LIMIT],'nasza_obrona_przeciwrakietowa':defenses[:LIMIT],'nasze_regiony':own_regions[:LIMIT],
          'regiony_przeciwnika':enemy_regions[:LIMIT],'miasta_przeciwnika':enemy_cities[:LIMIT],'cele_ataku_lądowego':land_targets[:LIMIT],
          'znane_bazy_przeciwnika':known[:LIMIT],
          'zasady':'Używaj wyłącznie numerów z tych list. Bez wojny panel wojenny jest niedostępny; nowe bazy: deploy w nasze_regiony.'}
    return {key:value for key,value in view.items() if value not in (None,[],{})}


def addressees_view(result):
    """Who can be written to: recipient_id is a PLAYER (user) id, not a country id."""
    items=(result or {}).get('items') if isinstance(result,dict) else None
    if items is None:return result
    return {'adresaci':[{'recipient_id':item.get('id'),'państwo':item.get('country_name'),'country_id':item.get('country_id')} for item in items[:40]],
            'uwaga':'recipient_id to numer gracza z tej listy (nie numer państwa).'}


def normalize(operation,data):
    """A small model writes 0 for 'none'. Absent value, not a decision: drop it before the player route."""
    if operation in ('game_forum.page:POST','game_messages.send:POST'):
        return {key:value for key,value in data.items() if not (key in ('reply_to_id','recipient_id') and value in (0,-1,None,''))}
    return data


def _object(properties,required):
    return {'type':'object','properties':properties,'required':required,'additionalProperties':False}

INT={'type':'integer','minimum':1}
COUNT={'type':'integer','minimum':0}


def variants(operation,relation_ids):
    """Exact data shapes per action. Values (ids, counts) still come from the model's reading of dane_gry."""
    if operation=='game_military.war_order:POST':
        targets={field:INT for field in TARGET_FIELDS}
        return {'anyOf':[
            _object({'kind':{'type':'string','enum':['land']},'region_id':INT,'source_base_id':INT,'soldiers':COUNT,'tanks':COUNT,'armored':COUNT},['kind','region_id']),
            _object({'kind':{'type':'string','enum':['missile']},'region_id':INT,'source_base_id':INT,'missile_type':{'type':'string','enum':MISSILES},'missiles':INT,
                     'infrastructure':{'type':'string','enum':INFRASTRUCTURE},**targets},['kind','region_id','source_base_id','missile_type','missiles']),
            _object({'kind':{'type':'string','enum':['air']},'region_id':INT,'source_base_id':INT,'fighters':COUNT,'drones':COUNT,
                     'infrastructure':{'type':'string','enum':INFRASTRUCTURE},**targets},['kind','region_id','source_base_id']),
            _object({'kind':{'type':'string','enum':['naval']},'region_id':INT,'vessel_id':INT,'source_base_id':INT,
                     'infrastructure':{'type':'string','enum':INFRASTRUCTURE},**targets},['kind','region_id'])]}
    if operation=='game_military.defense_change:POST':
        garrison={'type':'object','properties':{key:COUNT for key in ('soldiers','tanks','armored','launchers','fighters','warships','submarines','warheads')},'additionalProperties':False}
        def action(name,properties,required):return _object({'action':{'type':'string','enum':[name]},**properties},['action',*required])
        return {'anyOf':[
            action('deploy',{'kind':{'type':'string','enum':BASE_KINDS},'region_id':INT,'x':{'type':'number'},'y':{'type':'number'},'garrison':garrison},['kind','region_id','x','y','garrison']),
            action('place',{'kind':{'type':'string','enum':BASE_KINDS},'region_id':INT,'count':INT},['kind','region_id','count']),
            action('garrison',{'base_id':INT,'garrison':garrison},['base_id','garrison']),
            action('location',{'base_id':INT,'x':{'type':'number'},'y':{'type':'number'}},['base_id','x','y']),
            action('rename',{'base_id':INT,'name':{'type':'string','maxLength':60}},['base_id','name']),
            action('upgrade',{'base_id':INT},['base_id']),action('withdraw',{'base_id':INT},['base_id']),
            action('sail',{'base_id':INT,'vessel_kind':{'type':'string','enum':['warships','submarines']},'x':{'type':'number'},'y':{'type':'number'}},['base_id','vessel_kind','x','y']),
            action('return_vessel',{'vessel_id':INT,'base_id':INT},['vessel_id','base_id']),
            action('defense_place',{'target_kind':{'type':'string','enum':['region','city','base','mine','factory','power']},'target_id':INT},['target_kind','target_id']),
            action('defense_upgrade',{'defense_id':INT},['defense_id']),action('defense_refill',{'defense_id':INT,'ammunition':INT},['defense_id','ammunition']),
            action('defense_repair',{'defense_id':INT,'count':{'type':'integer','minimum':1,'maximum':100}},['defense_id','count'])]}
    if operation=='game_diplomacy.create_action:POST':
        options=[_object({'kind':{'type':'string','enum':[kind]},'target_id':INT},['kind','target_id']) for kind in ('WAR','PEACE','CEASEFIRE')]
        relation={'type':'integer','enum':sorted(relation_ids)} if relation_ids else INT
        options.append(_object({'kind':{'type':'string','enum':['RELATION']},'target_id':INT,'relation_id':relation},['kind','target_id','relation_id']))
        return {'anyOf':options}
    return None


def relation_choices(session):
    """Relation dictionary of the game (public rules): id -> name, for the RELATION variant and the context."""
    try:
        from game.diplomacy_service import dictionaries
        relations,_,_=dictionaries(session)
        return {int(id):name for id,name in relations.items()}
    except Exception:return {}
