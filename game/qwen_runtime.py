"""Text-only local Qwen, CPU bounded, no tools/files/DB access in the inference sandbox.

ModelSession keeps ONE llama-server process for several completions (optionally reusing the prompt cache);
`generate()` keeps the original one-shot behaviour. Memory guards, cancellation and time limits apply to both.
Runtime parameters come from settings() so they can be changed only after measurement.
"""
from pathlib import Path
import json,os,secrets,signal,socket,subprocess,threading,time,urllib.request,urllib.error
ROOT=Path(__file__).resolve().parents[1]/'runtime/qwen'
MODEL='Qwen3.5-4B-Q4_K_M.gguf'
START_MIN_AVAILABLE=3500*1024**2
STOP_MIN_AVAILABLE=1536*1024**2
MAX_RSS=4800*1024**2
REQUEST_SECONDS=300
MEMORY_WAIT_SECONDS=90
# Measured 2026-11-09: RSS grows ~0.3–0.5 GiB per call in one process (4.32→4.60→5.14 GiB). Two calls stay ≤4.61 GiB,
# so the process is recycled before a call once it exceeds this level (instead of being stopped mid-generation).
RECYCLE_RSS=int(4.45*1024**3)

class ContextTooLarge(ValueError):
    """The prompt does not fit the model window; the caller should send a smaller context."""


def settings():
    """Measured defaults (see docs/PAGA_AI_REBUILD.md); environment variables override for benchmarks only."""
    def number(name,default):
        try:return int(os.environ.get(name,default))
        except ValueError:return default
    # Benchmark 2026-11-09 (docs/paga-ai-benchmark.json): -t 6 -b 512 -ub 256 = 62 tok/s prompt vs 19.5 (-t 2 -b 64 -ub 32),
    # 71–79 s vs 175–187 s per decision, same RAM peak; cache_prompt reused ~34% of the prompt on the next call.
    return {'threads':number('PAGA_AI_THREADS',6),'batch':number('PAGA_AI_BATCH',512),'ubatch':number('PAGA_AI_UBATCH',256),
            'context':number('PAGA_AI_CONTEXT',4096),'cache_prompt':os.environ.get('PAGA_AI_CACHE_PROMPT','1')=='1'}

def available_memory():
    return next(int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))

def sandbox_command(port,key,config=None):
    config=config or settings()
    if not Path('/usr/bin/bwrap').is_file():raise RuntimeError('Brak izolacji procesu modelu.')
    binary=ROOT/'build/bin'
    threads=str(max(1,min(6,config['threads'])))
    command=['/usr/bin/bwrap','--die-with-parent','--unshare-pid','--unshare-ipc','--unshare-uts','--new-session','--clearenv','--ro-bind','/usr','/usr','--ro-bind','/lib','/lib']
    if Path('/lib64').exists():command+=['--ro-bind','/lib64','/lib64']
    if Path('/etc/ld.so.cache').exists():command+=['--ro-bind','/etc/ld.so.cache','/etc/ld.so.cache']
    return command+['--proc','/proc','--dev','/dev','--tmpfs','/tmp','--dir','/engine','--ro-bind',str(binary),'/engine','--dir','/models','--ro-bind',str(ROOT/MODEL),'/models/qwen.gguf','--chdir','/tmp','--setenv','PATH','/usr/bin:/bin','--setenv','LD_LIBRARY_PATH','/engine','--setenv','HOME','/tmp','--setenv','LANG','C.UTF-8','--','/usr/bin/nice','-n','10','/engine/llama-server','-m','/models/qwen.gguf','-c',str(config['context']),'-t',threads,'-tb',threads,'-b',str(config['batch']),'-ub',str(config['ubatch']),'-np','1','--host','127.0.0.1','--port',str(port),'--api-key',key,'--no-webui']

def process_rss(pid):
    try:
        total=next((int(line.split()[1])*1024 for line in Path(f'/proc/{pid}/status').read_text().splitlines() if line.startswith('VmRSS:')),0)
        for child in Path(f'/proc/{pid}/task/{pid}/children').read_text().split():total+=process_rss(int(child))
        return total
    except (OSError,ProcessLookupError):return 0


class ModelSession:
    """A single sandboxed llama-server reused for consecutive completions. Never more than one per worker lock."""
    def __init__(self,config=None):
        self.config=config or settings();self.process=None;self.peak=0;self.reason=[];self.calls=0
        self.cancelled=lambda:False;self.request_started=None;self.done=threading.Event();self.started=None
        self.minimum_available=None;self.last_success=False

    def start(self):
        if self.process is not None:return self
        if not (ROOT/MODEL).is_file() or not (ROOT/'build/bin/llama-server').is_file():raise RuntimeError('Model lokalny nie jest zainstalowany.')
        # Memory of a just-closed model process returns with a delay; wait briefly instead of failing the task.
        waited=time.monotonic()
        while available_memory()<START_MIN_AVAILABLE and time.monotonic()-waited<MEMORY_WAIT_SECONDS:time.sleep(3)
        if available_memory()<START_MIN_AVAILABLE:raise MemoryError('Za mało dostępnej pamięci na bezpieczny start Qwen 4B; zadanie nie zostało wykonane.')
        with socket.socket() as probe:probe.bind(('127.0.0.1',0));self.port=probe.getsockname()[1]
        self.key=secrets.token_urlsafe(32);self.started=time.monotonic();self.minimum_available=available_memory()
        log_fd=os.open(ROOT/'inference.log',os.O_CREAT|os.O_TRUNC|os.O_WRONLY,0o600)
        self.log=os.fdopen(log_fd,'wb')
        self.process=subprocess.Popen(sandbox_command(self.port,self.key,self.config),stdin=subprocess.DEVNULL,stdout=self.log,stderr=self.log,start_new_session=True,cwd=ROOT)
        self.monitor=threading.Thread(target=self._watch,daemon=True);self.monitor.start()
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));self.base=f'http://127.0.0.1:{self.port}'
        while True:
            if self.process.poll() is not None:raise RuntimeError(self.reason[-1] if self.reason else 'Silnik Qwen zakończył pracę przed gotowością.')
            try:
                request=urllib.request.Request(self.base+'/health',headers={'Authorization':'Bearer '+self.key})
                with self.opener.open(request,timeout=2) as response:
                    if response.status==200:break
            except OSError:pass
            if time.monotonic()-self.started>120:raise TimeoutError('Silnik Qwen nie osiągnął gotowości.')
            time.sleep(.3)
        return self

    def _stop(self):
        try:os.killpg(self.process.pid,signal.SIGTERM)
        except (ProcessLookupError,AttributeError):pass

    def _watch(self):
        while not self.done.wait(.5):
            self.peak=max(self.peak,process_rss(self.process.pid));self.minimum_available=min(self.minimum_available,available_memory())
            try:cancel=self.cancelled()
            except Exception:cancel=True
            if cancel and self.request_started is not None:self.reason.append('Zadanie anulowano przez wyłączenie AI lub przejęcie państwa.');self._stop();return
            if available_memory()<STOP_MIN_AVAILABLE or self.peak>MAX_RSS:self.reason.append('Przerwano generowanie, aby ochronić pamięć serwera gry.');self._stop();return
            if self.request_started is not None and time.monotonic()-self.request_started>REQUEST_SECONDS:self.reason.append('Przekroczono limit czasu modelu.');self._stop();return

    def generate(self,messages,*,cancelled=lambda:False,schema=None,stats=None,max_tokens=512):
        stats=stats if stats is not None else {}
        began=time.monotonic();success=False
        try:
            if self.process is not None and (process_rss(self.process.pid)>RECYCLE_RSS or self.process.poll() is not None):
                self.recycled=getattr(self,'recycled',0)+1;self.close();self.done=threading.Event();self.peak=0;self.reason=[]
            self.start()
            if self.process.poll() is not None:raise RuntimeError(self.reason[-1] if self.reason else 'Silnik Qwen nie działa.')
            self.cancelled=cancelled;self.request_started=time.monotonic()
            body={'messages':messages,'temperature':.3,'top_p':.9,'max_tokens':int(max_tokens),'stream':False,'cache_prompt':bool(self.config['cache_prompt']),
                  'chat_template_kwargs':{'enable_thinking':False},'response_format':{'type':'json_object'}}
            if schema:body['response_format']={'type':'json_object','schema':schema}
            request=urllib.request.Request(self.base+'/v1/chat/completions',data=json.dumps(body,ensure_ascii=False).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+self.key})
            try:
                with self.opener.open(request,timeout=REQUEST_SECONDS-40) as response:result=json.load(response)
            except urllib.error.HTTPError as error:
                text=error.read(2000).decode('utf-8','replace') if hasattr(error,'read') else ''
                if error.code==400 and 'exceeds the available context' in text:raise ContextTooLarge(text[:300]) from None
                raise
            timings=result.get('timings') or {};usage=result.get('usage') or {}
            stats.update(prompt_tokens=timings.get('prompt_n',usage.get('prompt_tokens')),prompt_ms=timings.get('prompt_ms'),generated_tokens=timings.get('predicted_n',usage.get('completion_tokens')),
                         generation_ms=timings.get('predicted_ms'),cached_tokens=timings.get('cache_n'))
            if cancelled():raise RuntimeError('Zadanie anulowano.')
            choice=result['choices'][0]
            if choice.get('finish_reason')=='length':raise ValueError('Ucięta odpowiedź modelu; nie wykonano dyspozycji.')
            decision=json.loads(choice['message']['content'])
            if not isinstance(decision,dict):raise ValueError('Model nie zwrócił obiektu JSON.')
            success=True;self.calls+=1;return decision
        except Exception:
            if self.reason:raise RuntimeError(self.reason[-1]) from None
            raise
        finally:
            self.request_started=None;self.cancelled=lambda:False;self.last_success=success
            stats.update(seconds=round(time.monotonic()-began,2),peak_rss_bytes=self.peak,minimum_available_bytes=self.minimum_available,success=success,reason=list(self.reason),
                         session_calls=self.calls,recycled=getattr(self,'recycled',0),threads=self.config['threads'],batch=self.config['batch'],ubatch=self.config['ubatch'],cache_prompt=self.config['cache_prompt'])

    def close(self):
        if self.process is None:return
        self.done.set()
        try:self.monitor.join(timeout=3)
        except Exception:pass
        self._stop()
        try:self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:os.killpg(self.process.pid,signal.SIGKILL);self.process.wait(timeout=5)
        try:self.log.close()
        except Exception:pass
        (ROOT/'last_inference.json').write_text(json.dumps({'seconds':round(time.monotonic()-self.started,2),'peak_rss_bytes':self.peak,'minimum_available_bytes':self.minimum_available,
                                                            'success':self.last_success,'reason':self.reason,'calls':self.calls,'config':self.config},ensure_ascii=False))
        self.process=None

    def __enter__(self):return self
    def __exit__(self,*exc):self.close()


def generate(messages,*,cancelled=lambda:False,schema=None,stats=None,max_tokens=512):
    """One completion in its own short-lived process (original behaviour)."""
    with ModelSession() as session:
        return session.generate(messages,cancelled=cancelled,schema=schema,stats=stats,max_tokens=max_tokens)
