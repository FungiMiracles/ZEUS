"""Słowniki profilu PAGA2: ogólny charakter, priorytety strategiczne, cechy i powiązania."""

MAX_CATEGORIES=3

# Ogólny charakter państwa (do trzech na państwo). Pola 'future' opisują elementy jeszcze niedostępne w grze.
CATEGORIES={
    'imperialist':{'label':'Państwo imperialistyczne','description':'Ekspansja terytorialna i siłowe podporządkowanie innych państw.'},
    'economic':{'label':'Państwo gospodarcze','description':'Wzrost gospodarczy, przemysł, wydobycie i handel.'},
    'welfare':{'label':'Państwo dobrobytu','description':'Wysoki poziom świadczeń, zdrowia i jakości życia obywateli.'},
    'isolationist':{'label':'Państwo izolacjonistyczne','description':'Samowystarczalność i ograniczanie zaangażowania za granicą.'},
    'terrorist':{'label':'Państwo terrorystyczne','description':'Destabilizacja innych państw: dywersja, sabotaż i zastraszanie.'},
    'hegemonic':{'label':'Państwo hegemonistyczne','description':'Budowa międzynarodowych sojuszy i strefy wpływów.',
                 'future':['Budowa baz wojskowych w innych krajach','Eksploatacja złóż w innych krajach']},
}

# Priorytety strategiczne — administrator wybiera kilka i układa je od najważniejszego.
PRIORITIES={
    'infrastructure':'Rozwój infrastruktury',
    'research':'Rozwój badań i nauki',
    'offensive_army':'Rozwój armii ofensywnej',
    'defensive_army':'Rozwój armii defensywnej',
    'welfare':'Rozwój państwa opiekuńczego',
    'trade':'Rozwój handlu międzynarodowego',
    'production':'Rozwój produkcji i technologii',
    'environment':'Ochrona środowiska',
    'conquest':'Podbój nowych terytoriów',
    'intelligence':'Rozwój wywiadu',
    'financial_stability':'Stabilność finansowa',
    'alliances':'Budowa sojuszy',
}

# Charakterystyka państwa, wartości 0–100. Pierwsze siedem kluczy jest wspólnych z dotychczasową konfiguracją PAGA.
TRAITS={
    'agreeableness':'Ugodowość',
    'predictability':'Przewidywalność',
    'militarism':'Militaryzm',
    'provocation':'Prowokacyjność',
    'isolationism':'Izolacjonizm',
    'revenge':'Rewanżyzm',
    'ambition':'Ambicja',
    'expansionism':'Ekspansjonizm',
    'alliance_loyalty':'Lojalność sojusznicza',
    'interventionism':'Interwencjonizm',
    'solidarity':'Solidarność międzynarodowa',
    'regional_dominance':'Dominacja regionalna',
    'loss_tolerance':'Tolerancja strat',
    'fiscal_conservatism':'Konserwatyzm fiskalny',
    'industrialism':'Proindustrialność',
    'debt_tolerance':'Tolerancja zadłużenia',
    'trade_propensity':'Skłonność do handlu',
    'prosociality':'Prospołeczność',
    'ecology':'Proekologiczność',
    'health':'Prozdrowotność',
    'espionage':'Skłonność do szpiegostwa',
    'subversion':'Dywersyjność',
    'secrecy':'Skrytość',
    'strategic_patience':'Cierpliwość strategiczna',
    'strategic_flexibility':'Elastyczność strategiczna',
}
DEFAULT_TRAIT=50

# Powiązania między państwami — zapisywane w istniejącej tabeli game_paga_relationships.
RELATIONSHIPS={'historical_ally':'Historyczni sojusznicy','historical_hostile':'Historycznie nieprzyjazne','satellite':'Państwo satelickie'}


class ProfileError(ValueError):pass


def validate_profile(data):
    """Zwraca (categories, priorities, traits) albo rzuca ProfileError z komunikatem dla administratora."""
    if not isinstance(data,dict):raise ProfileError('Nieprawidłowe dane profilu.')
    categories=data.get('categories');priorities=data.get('priorities');traits=data.get('traits')
    if not isinstance(categories,list) or not all(isinstance(key,str) for key in categories):raise ProfileError('Ogólny charakter musi być listą.')
    if len(set(categories))!=len(categories) or not set(categories)<=set(CATEGORIES):raise ProfileError('Nieznany lub powtórzony ogólny charakter państwa.')
    if not 1<=len(categories)<=MAX_CATEGORIES:raise ProfileError(f'Wybierz od 1 do {MAX_CATEGORIES} opcji ogólnego charakteru państwa.')
    if not isinstance(priorities,list) or not all(isinstance(key,str) for key in priorities):raise ProfileError('Priorytety muszą być listą.')
    if len(set(priorities))!=len(priorities) or not set(priorities)<=set(PRIORITIES):raise ProfileError('Nieznany lub powtórzony priorytet strategiczny.')
    if not priorities:raise ProfileError('Wybierz co najmniej jeden priorytet strategiczny.')
    if not isinstance(traits,dict) or set(traits)!=set(TRAITS):raise ProfileError('Przekaż wszystkie cechy państwa.')
    for key,value in traits.items():
        if type(value) is not int or not 0<=value<=100:raise ProfileError(f'{TRAITS[key]}: podaj liczbę całkowitą od 0 do 100.')
    return list(categories),list(priorities),dict(traits)


def priority_weights(priorities):
    """Wagi malejące liniowo z pozycją; suma 1. Pierwszy priorytet waży najwięcej."""
    n=len(priorities)
    if not n:return {}
    total=n*(n+1)/2
    return {key:(n-rank)/total for rank,key in enumerate(priorities)}


def default_profile(old_character=None):
    """Profil startowy: siedem cech przejętych z dotychczasowej konfiguracji PAGA, pozostałe 50."""
    traits={key:DEFAULT_TRAIT for key in TRAITS}
    for key,value in (old_character or {}).items():
        if key in traits and type(value) is int and 0<=value<=100:traits[key]=value
    return traits
