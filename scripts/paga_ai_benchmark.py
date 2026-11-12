"""Measured llama.cpp settings for PAGA AI (stage 6). One model instance at a time, bounded time, isolated data.

Uses a realistic decision prompt (system prompt + strategic-review context + grammar) captured from the isolated
fixture, runs each configuration in its own ModelSession with two consecutive calls (second one shares the prompt
prefix, to measure cache_prompt), and samples the UAT web latency meanwhile (read-only GET of the entry page /wejscie).

    venv/bin/python scripts/paga_ai_benchmark.py --max-minutes 35
"""
import sys,json,time,fcntl,argparse,subprocess,signal,threading,urllib.request,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT)]

CONFIGS=[(2,64,32,False),(4,512,256,False),(6,512,256,False)]


def free_gib():
    return next(int(line.split()[1])/1024**2 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))


def captured_prompt():
    """Real messages+schema of a strategic review, produced by the isolated fixture with a stand-in model."""
    import test_paga_ai_tasks as scenario
    case=scenario.AiScenarioTests.__new__(scenario.AiScenarioTests);__import__('unittest').TestCase.__init__(case);case.setUp()
    try:
        from unittest.mock import patch
        captured={}
        def model(messages,**kwargs):
            captured.update(messages=messages,schema=kwargs.get('schema'));return {'ocena':'x','actions':[],'task_done':True}
        with patch('game.qwen_runtime.generate',side_effect=model):
            from engine.paga_ai_scheduler import run_tick
            run_tick(case.app)
        return captured
    finally:case.tearDown()


class WebProbe(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True);self.samples=[];self.stop=threading.Event()
    def run(self):
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        while not self.stop.wait(5):
            began=time.monotonic()
            try:
                with opener.open('http://127.0.0.1:5001/wejscie',timeout=10) as response:response.read(1)
                self.samples.append(round((time.monotonic()-began)*1000))
            except Exception:self.samples.append(None)


def measure(config,prompt):
    from game import qwen_runtime
    threads,batch,ubatch,cache=config
    settings={'threads':threads,'batch':batch,'ubatch':ubatch,'context':4096,'cache_prompt':cache}
    probe=WebProbe();probe.start();calls=[];load_before=os.getloadavg()[0]
    try:
        with qwen_runtime.ModelSession(settings) as session:
            for index in range(2):
                messages=[dict(item) for item in prompt['messages']]
                if index:messages[1]['content']=messages[1]['content'].replace('"przebieg_zadania": []','"przebieg_zadania": [{"krok": "decyzja 1", "ocena": "Odczyt danych."}]')
                stats={};began=time.monotonic()
                try:
                    decision=session.generate(messages,schema=prompt['schema'],stats=stats,max_tokens=200)
                    calls.append({'ok':True,'wall_s':round(time.monotonic()-began,1),**{k:stats.get(k) for k in ('prompt_tokens','prompt_ms','generated_tokens','generation_ms','cached_tokens','peak_rss_bytes','minimum_available_bytes')},'actions':[a.get('operation_id') for a in decision.get('actions',[])]})
                except Exception as error:
                    calls.append({'ok':False,'wall_s':round(time.monotonic()-began,1),'error':f'{type(error).__name__}: {error}'[:200],**{k:stats.get(k) for k in ('peak_rss_bytes','minimum_available_bytes')}})
    finally:
        probe.stop.set();probe.join(timeout=6)
    web=[value for value in probe.samples if value is not None]
    return {'threads':threads,'batch':batch,'ubatch':ubatch,'cache_prompt':cache,'calls':calls,'load_before':load_before,'load_after':os.getloadavg()[0],
            'web_ms_median':sorted(web)[len(web)//2] if web else None,'web_ms_max':max(web) if web else None,'web_failures':probe.samples.count(None)}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--max-minutes',type=int,default=35);parser.add_argument('--output',default=str(ROOT/'docs'/'paga-ai-benchmark.json'));args=parser.parse_args()
    lock_path=ROOT/'runtime/qwen/worker.lock'
    with lock_path.open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise SystemExit('Model jest zajęty przez scheduler UAT lub inną sesję; benchmark nie startuje.')
        if subprocess.run(['pgrep','-x','llama-server'],capture_output=True).stdout.strip():raise SystemExit('Działa inna instancja llama-server.')
        if free_gib()<4.0:raise SystemExit(f'Za mało wolnej pamięci: {free_gib():.2f} GiB.')
        def timeout(*_):raise TimeoutError('Przekroczono limit czasu benchmarku.')
        signal.signal(signal.SIGALRM,timeout);signal.alarm(args.max_minutes*60)
        prompt=captured_prompt()
        evidence={'cpu':os.cpu_count(),'free_gib_start':round(free_gib(),2),'prompt_chars':{'system':len(prompt['messages'][0]['content']),'user':len(prompt['messages'][1]['content'])},'results':[]}
        try:
            idle=WebProbe();idle.start();time.sleep(16);idle.stop.set();idle.join(timeout=6)
            evidence['web_ms_idle']=[value for value in idle.samples if value is not None]
            configs=list(CONFIGS)
            for config in configs:
                print('Konfiguracja',config,flush=True);evidence['results'].append(measure(config,prompt));print(json.dumps(evidence['results'][-1],ensure_ascii=False),flush=True)
            def speed(result):
                ok=[call for call in result['calls'] if call['ok']];return sum(call['wall_s'] for call in ok)/len(ok) if ok else 1e9
            best=min(evidence['results'],key=speed)
            for extra in ((best['threads'],256,128,False),(best['threads'],best['batch'],best['ubatch'],True)):
                print('Konfiguracja',extra,flush=True);evidence['results'].append(measure(extra,prompt));print(json.dumps(evidence['results'][-1],ensure_ascii=False),flush=True)
        except TimeoutError as error:evidence['stopped']=str(error)
        finally:
            signal.alarm(0);evidence['free_gib_end']=round(free_gib(),2)
            Path(args.output).write_text(json.dumps(evidence,ensure_ascii=False,indent=1,default=str));print('Zapisano',args.output,flush=True)


if __name__=='__main__':main()
