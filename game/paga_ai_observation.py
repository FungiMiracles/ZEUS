"""Project *player responses*, never ORM records, into model-visible observations."""
import json,re
from html.parser import HTMLParser

SECRET=re.compile(r'csrf|password|passwd|cookie|authorization|session|secret|email|api.?key|access.?token|paga.?access|traceback|stacktrace',re.I)
TECHNICAL=re.compile(r'(?:url|icon|flag|flag_path|css|script|implementation|sql)$',re.I)

def scrub(value,*,depth=0):
    if depth>14:return '[zbyt głęboka struktura]'
    if isinstance(value,dict):
        result={}
        for key,item in value.items():
            if SECRET.search(str(key)) or TECHNICAL.search(str(key)):continue
            if key in {'basis_token','_budget_plan','_retry_state','_retry_command','headers','environ','request','config','credentials','password_hash'}:continue
            result[str(key)]=scrub(item,depth=depth+1)
        return result
    if isinstance(value,list):return [scrub(item,depth=depth+1) for item in value]
    if value is None or type(value) in (str,int,float,bool):return value
    return str(value)

class PlayerDocument(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.skip=0;self.script=None;self.script_parts=[];self.facts=[];self.text=[];self.forms=[];self.active_form=None;self.links=[];self.active_link=None
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='script':
            self.script=a.get('type')=='application/json';self.script_parts=[];self.skip+=1;return
        if tag in {'style','nav','footer'}:self.skip+=1
        if tag=='a' and a.get('href','').startswith('/game/'):
            self.active_link={'href':a['href'],'label':''};self.links.append(self.active_link)
        if tag=='form':self.active_form={'fields':[]};self.forms.append(self.active_form)
        if tag in {'input','select','textarea'} and self.active_form is not None:
            name=a.get('name','')
            if name and not SECRET.search(name) and (a.get('type') not in {'password','hidden'} or name in {'version','reply_to_id'}):
                self.active_form['fields'].append({key:a[key] for key in ['name','type','min','max','value','required'] if key in a})
    def handle_endtag(self,tag):
        if tag=='script':
            if self.script:
                try:self.facts.append(scrub(json.loads(''.join(self.script_parts))))
                except (ValueError,TypeError):pass
            self.script=None;self.skip=max(0,self.skip-1)
        if tag in {'style','nav','footer'}:self.skip=max(0,self.skip-1)
        if tag=='a':self.active_link=None
        if tag=='form':self.active_form=None
    def handle_data(self,data):
        if self.script:self.script_parts.append(data)
        if not self.skip and data.strip():self.text.append(data.strip())
        if self.active_link is not None:self.active_link['label']+=data.strip()
    def observation(self):
        from flask import current_app
        from urllib.parse import urlsplit,parse_qs
        actions=[]
        for link in self.links:
            try:
                url=urlsplit(link['href']);endpoint,path=current_app.url_map.bind('').match(url.path,method='GET')
                from game.player_operations import catalogue
                if endpoint+':GET' not in catalogue():continue
                values={key:([int(v) if v.isdigit() else v for v in value] if len(value)>1 else int(value[0]) if value[0].isdigit() else value[0]) for key,value in parse_qs(url.query).items()}
                actions.append({'label':link['label'],'operation_id':endpoint+':GET','path':path,'data':values})
            except Exception:continue
        return {'game_data':self.facts,'forms':self.forms,'actions':actions,'visible_text':'\n'.join(self.text)}

def observe_response(response):
    if response.status_code>=500:return {'error':'Błąd serwera. Odczytaj stan przed ponowieniem operacji.'}
    if response.is_json:return scrub(response.get_json())
    if 300<=response.status_code<400:return {'message':'Operacja zakończona. Możesz ponownie odczytać odpowiedni ekran gry.'}
    document=PlayerDocument();document.feed(response.get_data(as_text=True));return scrub(document.observation())

def window(value,offset=0,limit=12000):
    """Bound context, with explicit pagination instead of silently dropping game facts."""
    raw=json.dumps(value,ensure_ascii=False,default=str)
    return {'text':raw[offset:offset+limit],'offset':offset,'next_offset':offset+limit if len(raw)>offset+limit else None,'total_characters':len(raw)}
