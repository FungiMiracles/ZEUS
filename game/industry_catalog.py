"""Rules transcribed from WYM0060–0071; unspecified parameters stay unset."""
TECHNOLOGIES={}
def tech(code,label,cost,parent,branch,icon='research',requires=None):
    # requires: wszystkie technologie wymagane do rozpoczęcia badań (domyślnie tylko rodzic w drzewie; 13 Nov 2026)
    TECHNOLOGIES[code]=dict(label=label,cost=cost,parent=parent,branch=branch,icon=icon,requires=list(requires) if requires else ([parent] if parent else []))
tech('method','Metoda badawcza',25,None,'method')
for code,label,cost,parent,icon in [
('arms_industry','Krajowy przemysł zbrojeniowy',25,'method','army'),('short_missiles','Rakiety krótkiego zasięgu',100,'arms_industry','missile_launcher'),('interceptor_ammo','Amunicja przeciwrakietowa',20,'arms_industry','ammo'),('medium_missiles','Rakiety średniego zasięgu',200,'short_missiles','missile_launcher'),('long_missiles','Rakiety dalekiego zasięgu',350,'medium_missiles','missile_launcher'),('drones','Drony',40,'arms_industry','drone'),('fighters','Myśliwce',120,'drones','army'),('armored','Wozy opancerzone',65,'arms_industry','armored_vehicle'),('tanks','Czołgi',100,'armored','tank'),('warship','Okręt',120,'arms_industry','warship'),('submarine','Okręt podwodny',250,'warship','submarine'),('carrier','Lotniskowiec',400,'warship','aircraft_carrier')]:tech(code,label,cost,parent,'military',icon)
tech('mining_industry','Krajowy przemysł wydobywczy',25,'method','mining','mine')
for code,label,cost in [('coal','Wydobycie węgla',25),('oil','Wydobycie ropy naftowej',100),('surface','Wydobycie odkrywkowe',50),('kerbit','Wydobycie kerbitu',200),('natsyt','Wydobycie natsytu',250),('cemium','Wydobycie cemium',500),('uranium','Wydobycie uranu',500)]:tech('mine_'+code,label,cost,'mining_industry','mining','mine')
tech('mine_iron','Wydobycie żelaza',75,'mining_industry','mining','mine')
tech('it_industry','Krajowy przemysł IT',30,'method','it','computer');parent='it_industry'
for code,label,cost in [('simple','Chip prosty',100),('kerbit','Chip kerbitowy',200),('natsyt','Chip natsytowy',300),('cemium_i','Chip cemium I',700),('cemium_ii','Chip cemium II',1000)]:
    tech('chip_'+code,label,cost,parent,'it','computer');parent='chip_'+code
# Radar reconnaissance (administrator, 11 Nov 2026): branches off the natsyt chip; unlocks radars on the defence map.
tech('radar','Rozpoznanie radarowe',600,'chip_natsyt','it','radar')
tech('energy_industry','Krajowa produkcja energii',15,'method','energy','energy')
for code,label,cost in [('coal','Elektrownia węglowa',15),('nuclear','Elektrownia atomowa',350),('wind','Elektrownia wiatrowa',100),('solar','Elektrownia słoneczna',150)]:tech('power_'+code,label,cost,'energy_industry','energy','energy')
# Environmental protection branch (administrator rules, 10 Nov 2026): pollution filter for coal power plants (previously
# the planned 'Filtry powietrza' node under power_coal) and waste filter for factories.
tech('environment_tech','Technologie ochrony środowiska',30,'method','environment','environment')
tech('air_filters','Filtr zanieczyszczeń',150,'environment_tech','environment','air_filter')
tech('waste_filters','Filtr odpadów fabrycznych',120,'environment_tech','environment','waste_filter')
# Rakieta z głowicą nuklearną (13 Nov 2026): 750 pkt; wymaga rakiet dalekiego zasięgu, wydobycia uranu i chipu cemium I.
# Kolej (administrator, 19 Nov 2026): krajowe węzły komunikacyjne → transport kolejowy (zakładka „Komunikacja” w infrastrukturze).
tech('national_hubs','Krajowe węzły komunikacyjne',50,'method','transport','infrastructure')
tech('rail_transport','Transport kolejowy',200,'national_hubs','transport','rail')
tech('nuclear_missiles','Rakieta z głowicą nuklearną',750,'long_missiles','military','nuclear_weapon',requires=('long_missiles','mine_uranium','chip_cemium_i'))
# Descriptions displayed beneath research requirements and progress.
TECHNOLOGY_DESCRIPTIONS={
    'nuclear_missiles': 'Umożliwia budowę fabryki rakiet z głowicą nuklearną, produkcję rakiet atomowych, ich składowanie w silosach i odpalenie z terytorium kraju (zasięg 3000 km).',
    'arms_industry': 'Umożliwia produkowanie własnego uzbrojenia.',
    'method': 'Metoda badawcza umożliwia rozwój badań naukowych w kraju.',
    'energy_industry': 'Umożliwia produkowanie energii elektrycznej w kraju.',
    'power_solar': 'Umożliwia budowę farm paneli słonecznych.',
    'power_wind': 'Umożliwia budowanie farm wiatrowych.',
    'power_nuclear': 'Umożliwia budowanie elektrowni atomowych zasilanych uranem.',
    'power_coal': 'Umożliwia budowanie elektrowni zasilanych węglem.',
    'environment_tech': 'Umożliwia rozwój technologii chroniących powietrze i środowisko przed skutkami przemysłu i energetyki.',
    'waste_filters': 'Umożliwia montaż filtrów odpadów fabrycznych: fabryka z filtrem nie zwiększa degradacji środowiska w regionie.',
    'air_filters': 'Umożliwia montaż filtrów zanieczyszczeń na elektrowniach węglowych: elektrownia z filtrem nie zwiększa zanieczyszczenia powietrza w regionie.',
    'it_industry': 'Umożliwia rozpoczęcie rozwoju nad krajowymi technologiami informatycznymi.',
    'mine_coal': 'Umożliwia budowę kopalń węgla kamiennego, potrzebnego do produkcji energii i budowy okrętów.',
    'mine_oil': 'Umożliwia budowę szybów naftowych.',
    'mine_surface': 'Umożliwia budowę kopalń kamienia, złota i srebra.',
    'mine_kerbit': 'Umożliwia budowę kopalń kerbitu - niebieskiego minerału, wykorzystywanego w przemyśle technologicznym I stopnia.',
    'mine_natsyt': 'Umożliwia budowę kopalń natsytu - pomarańczowego minerału, wykorzystywanego w przemyśle technologicznym II stopnia.',
    'mine_cemium': 'Umożliwia budowę kopalń cemium - rzadkiego żółtego minerału, wykorzystywanego w przemyśle technologicznym III i IV stopnia.',
    'mine_uranium': 'Umożliwia budowę kopalń uranu, potrzebnego do produkcji energii z atomu.',
    'mine_iron': 'Umożliwia budowę kopalń żelaza, potrzebnego do tworzenia np. broni dla wojska.',
    'drones': 'Umożliwia produkcję własnych tanich dronów.',
    'fighters': 'Umożliwia produkcję własnych myśliwców.',
    'warship': 'Umożliwia produkcję własnych okrętów.',
    'carrier': 'Umożliwia produkcję własnych lotniskowców do przenoszenia myśliwców na duże odległości.',
    'submarine': 'Umożliwia produkcję własnych okrętów podwodnych.',
    'interceptor_ammo': 'Umożliwia produkcję własnej amunicji do obrony przeciwrakietowej.',
    'short_missiles': 'Umożliwia produkcję własnych rakiet lecących na odległość do 500 km.',
    'medium_missiles': 'Umożliwia produkcję własnych rakiet lecących na odległość do 2000 km.',
    'long_missiles': 'Umożliwia produkcję własnych rakiet lecących na odległość do 10 000 km.',
    'armored': 'Umożliwia produkcję wozów opancerzonych potrzebnych do inwazji lądowych i obrony kraju.',
    'tanks': 'Umożliwia produkcję czołgów potrzebnych do inwazji lądowych i obrony kraju.',
    'chip_simple': 'Pozwala na produkcję prostych chipów wykorzystywanych m.in. w czołgach.',
    'chip_kerbit': 'Pozwala na produkcję kerbitowych chipów wykorzystywanych m.in. w dronach.',
    'chip_natsyt': 'Pozwala na produkcję natsytowych chipów wykorzystywanych m.in. w rakietach dalekiego zasięgu.',
    'radar': 'Umożliwia budowę radarów na ekranie „Obrona państwa”. Radar wykrywa obce rakiety i samoloty w promieniu 400 / 800 / 1200 km (poziom I / II / III) i powiadamia o ich liczbie i celu.',
    'chip_cemium_i': 'Pozwala na produkcję chipów z cemium wykorzystywanych m.in. w rakietach przenoszących ładunki jądrowe.',
    'chip_cemium_ii': 'Pozwala na produkcję chipów z cemium II wykorzystywanych m.in. w budowie sztucznej inteligencji i superkomputerów.',
}
for key,description in TECHNOLOGY_DESCRIPTIONS.items():TECHNOLOGIES[key]['description']=description

MINE_RULES={
'wegiel_kamienny':('Kopalnia węgla kamiennego','mine_coal',[2,4,6],[1,3,5],5),'ropa_naftowa':('Szyb naftowy','mine_oil',[8,12,16],[1,3,5],12),'zloto':('Kopalnia złota','mine_surface',[3,5,7],[1,3,5],2),'srebro':('Kopalnia srebra','mine_surface',[3,5,7],[1,3,5],2),'kamien':('Kopalnia kamienia','mine_surface',[1,2,3],[3,6,9],2),'natsyt':('Kopalnia natsytu','mine_natsyt',[6,12,18],[1,3,5],7),'kerbit':('Kopalnia kerbitu','mine_kerbit',[8,14,21],[1,3,5],6),'cemium':('Kopalnia cemium','mine_cemium',[12,24,32],[1,3,5],'month'),'zelazo':('Kopalnia żelaza','mine_iron',[3,4,6],[1,3,5],5),'uran':('Kopalnia uranu','mine_uranium',[20,25,35],[1,3,5],14)}
GOODS={code:(label,file+'.svg') for code,label,file in [('chip_simple','Prosty chip','CHIP PROSTY'),('chip_kerbit','Chip kerbitowy','CHIP KERBITOWY'),('chip_natsyt','Chip natsytowy','CHIP NATSYTOWY'),('chip_cemium_i','Chip cemium I','CHIP CEMIUM I'),('chip_cemium_ii','Chip cemium II','CHIP CEMIUM II'),('tanks','Czołgi','CZOŁG'),('fighters','Myśliwce','MYŚLIWIEC'),('armored','Wozy opancerzone','WÓZ OPANCERZONY'),('drones','Drony','DRON'),('short_missiles','Rakiety krótkiego zasięgu','WYRZUTNIA RAKIET'),('medium_missiles','Rakiety średniego zasięgu','WYRZUTNIA RAKIET'),('long_missiles','Rakiety dalekiego zasięgu','WYRZUTNIA RAKIET')]}
ARMY_GOODS=dict(tanks='czolgi_ilosc',fighters='mysliwce_ilosc',armored='wozy_opancerzone_ilosc',drones='drony_ilosc',short_missiles='rakiety_krotkiego_zasiegu',medium_missiles='rakiety_sredniego_zasiegu',long_missiles='rakiety_dalekiego_zasiegu',warships='okrety_wojenne_ilosc',submarines='okrety_podwodne_ilosc',carriers='lotniskowce_ilosc')
FACTORIES={}
# Dzienny pobór energii fabryk (e/dzień, wg poziomu) — zmiana administratora 18 Nov 2026.
def recipe(cost,techs,product,inputs,energy,quantity,days):return dict(cost=int(cost*1000000000),technologies=techs,product=product,inputs=inputs,energy=energy,quantity=quantity,days=days)
def factory(code,label,levels):FACTORIES[code]=dict(label=label,levels=levels,icon='FABRYKA.svg')
factory('interceptor_ammo','Fabryka amunicji przeciwrakietowej',[recipe(2,['interceptor_ammo'],'interceptor_ammunition',{'zelazo':1,'ropa_naftowa':1},30,5,1)])
factory('tanks','Fabryka czołgów',[recipe(3,['tanks'],'tanks',{'zelazo':10,'ropa_naftowa':5,'chip_simple':1},10,1,7)])
factory('fighters','Fabryka myśliwców',[recipe(10,['fighters'],'fighters',{'zelazo':12,'ropa_naftowa':7,'chip_kerbit':1},150,1,7)])
factory('shipyard','Stocznia',[recipe(8,['warship'],'warships',{'zelazo':41,'ropa_naftowa':35,'wegiel_kamienny':66},400,1,'month'),recipe(15,['submarine'],'submarines',{'zelazo':67,'ropa_naftowa':41,'wegiel_kamienny':71,'chip_natsyt':1},800,1,'month'),recipe(21,['carrier'],'carriers',{'zelazo':112,'ropa_naftowa':97,'wegiel_kamienny':121,'chip_natsyt':5},1200,1,'month')])
factory('drones','Fabryka dronów',[recipe(4,['drones'],'drones',{'zelazo':3,'chip_kerbit':1},20,5,1)])
factory('missiles','Fabryka rakiet',[recipe(8,['short_missiles'],'short_missiles',{'zelazo':7,'ropa_naftowa':7,'chip_kerbit':1},40,1,1),recipe(16,['medium_missiles'],'medium_missiles',{'zelazo':10,'ropa_naftowa':14,'chip_kerbit':2},80,1,1),recipe(32,['long_missiles'],'long_missiles',{'zelazo':12,'ropa_naftowa':28,'chip_natsyt':2},120,1,1)])
factory('armored','Fabryka wozów opancerzonych',[recipe(7,['armored'],'armored',{'zelazo':15,'ropa_naftowa':6},50,1,7)])
factory('chips','Fabryka chipów',[recipe(8,['chip_simple'],'chip_simple',{'zelazo':1,'srebro':1,'zloto':1},35,10,1),recipe(16,['chip_kerbit'],'chip_kerbit',{'kerbit':2,'srebro':2,'zloto':2},50,6,1),recipe(32,['chip_natsyt'],'chip_natsyt',{'natsyt':2,'srebro':3,'zloto':3},75,4,1),recipe(48,['chip_cemium_i'],'chip_cemium_i',{'cemium':3,'zloto':5,'srebro':4},100,1,1),recipe(64,['chip_cemium_ii'],'chip_cemium_ii',{'cemium':4,'kerbit':1,'natsyt':1,'zloto':7,'srebro':5},125,1,1)])
# Fabryka rakiet z głowicą nuklearną (13 Nov 2026): 37,4 mld ROI z budżetu sił zbrojnych, budowa 31 dni Entendy; produkuje
# wyłącznie na zamówienie (game.nuclear) — 1 rakieta / 14 dni, na sztukę 7 uranu, 37 żelaza i 1 chip cemium I; pobór 700 e/dzień w trakcie realizacji zamówienia (18 Nov 2026).
factory('nuclear_missiles','Fabryka rakiet z głowicą nuklearną',[recipe(37.4,['nuclear_missiles'],'nuclear_missiles',{'uran':7,'zelazo':37,'chip_cemium_i':1},700,1,14)])
FACTORIES['nuclear_missiles'].update(on_demand=True,build_days=31,budget_sector='armed_forces',icon='FABRYKA.svg')
POWER_PLANTS={}
for code,label,costs,production,fuel,amounts in [('coal','Elektrownia węglowa',[2300000000,4400000000,6800000000],[100,200,300],'wegiel_kamienny',[1,2,3]),('nuclear','Elektrownia atomowa',[25700000000,36300000000,53500000000],[1000,2000,3000],'uran',[1,2,3]),('wind','Elektrownia wiatrowa',[40000000,1200000000,1600000000],[10,20,30],None,[0,0,0]),('solar','Elektrownia słoneczna',[50000000,1000000000,1300000000],[12,24,36],None,[0,0,0])]:POWER_PLANTS[code]=dict(label=label,technology='power_'+code,costs=costs,production=production,fuel=fuel,amounts=amounts,icon=label.upper()+'.svg')

# Icon identifiers share the existing static/icons mapping.
for code,icon in {'mine_coal':'Węgiel kamienny','mine_oil':'Ropa naftowa','mine_surface':'Kamień','mine_kerbit':'Kerbit','mine_natsyt':'Natsyt','mine_cemium':'Cemium','mine_uranium':'Uran','mine_iron':'Żelazo','chip_simple':'chip_simple','chip_kerbit':'chip_kerbit','chip_natsyt':'chip_natsyt','chip_cemium_i':'chip_cemium_i','chip_cemium_ii':'chip_cemium_ii','power_coal':'power_coal','power_nuclear':'power_nuclear','power_wind':'power_wind','power_solar':'power_solar'}.items():
    TECHNOLOGIES[code]['icon']=icon

# Visible future branches have no price and cannot receive research investments.
PLANNED_TECHNOLOGIES={}   # 13 Nov 2026: „Rakieta z głowicą nuklearną” jest aktywną technologią (TECHNOLOGIES)
RESEARCH_TECHNOLOGIES={**TECHNOLOGIES,**PLANNED_TECHNOLOGIES}

# Air pollution of coal power plants (administrator rules, 10 Nov 2026): each coal plant without a filter adds
# COAL_POLLUTION points to its region; liquidation removes them. Filter price depends on the plant level (ROI).
COAL_POLLUTION=2
FILTER_TECHNOLOGY='air_filters'
FILTER_COSTS=[500000000,700000000,900000000]
# Environmental degradation of factories: each factory without a waste filter adds FACTORY_DEGRADATION points to its
# region. Waste filter price per factory level (levels 4–5 continue the +0.2 MLD step; administrator, 10 Nov 2026).
FACTORY_DEGRADATION=2
WASTE_FILTER_TECHNOLOGY='waste_filters'
WASTE_FILTER_COSTS=[1100000000,1300000000,1500000000,1700000000,1900000000]
# Filters are paid from the environmental protection budget sector.
FILTER_SECTOR='environment'
