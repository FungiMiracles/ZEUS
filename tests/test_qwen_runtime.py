"""Model session behaviour without starting a real model: one process per session, lazy start, limits."""
import io,json,os,unittest
from unittest.mock import patch,MagicMock
from game import qwen_runtime


class FakeResponse(io.BytesIO):
    status=200
    def __enter__(self):return self
    def __exit__(self,*args):return False


def completion(payload,finish='stop'):
    return FakeResponse(json.dumps({'choices':[{'finish_reason':finish,'message':{'content':json.dumps(payload)}}],
                                    'timings':{'prompt_n':1500,'prompt_ms':30000,'predicted_n':90,'predicted_ms':12000,'cache_n':1200}}).encode())


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.popen=MagicMock();self.popen.return_value.poll.return_value=None;self.popen.return_value.pid=99999
        self.requests=[]
        def opener_open(request,timeout=None):
            self.requests.append(request)
            if request.full_url.endswith('/health'):return FakeResponse(b'{}')
            body=json.loads(request.data);self.bodies.append(body)
            return completion({'ok':len(self.bodies)})
        self.bodies=[]
        opener=MagicMock();opener.open.side_effect=opener_open
        patches=[patch('game.qwen_runtime.subprocess.Popen',self.popen),patch('game.qwen_runtime.urllib.request.build_opener',return_value=opener),
                 patch('game.qwen_runtime.available_memory',return_value=6*1024**3),patch('game.qwen_runtime.process_rss',return_value=10),
                 patch('game.qwen_runtime.os.killpg'),patch('pathlib.Path.is_file',return_value=True),
                 patch('game.qwen_runtime.os.open',side_effect=lambda *args,_open=os.open,**kwargs:_open(os.devnull,os.O_WRONLY)),
                 patch.object(qwen_runtime.Path,'write_text')]
        for item in patches:item.start();self.addCleanup(item.stop)

    def test_session_starts_lazily_and_reuses_one_process(self):
        session=qwen_runtime.ModelSession({'threads':4,'batch':256,'ubatch':128,'context':4096,'cache_prompt':True})
        self.assertEqual(self.popen.call_count,0,'nothing starts before a decision is needed')
        stats=[{},{}]
        self.assertEqual(session.generate([{'role':'user','content':'a'}],stats=stats[0]),{'ok':1})
        self.assertEqual(session.generate([{'role':'user','content':'b'}],stats=stats[1]),{'ok':2})
        session.close()
        self.assertEqual(self.popen.call_count,1)
        command=self.popen.call_args[0][0]
        self.assertEqual(command[command.index('-t')+1],'4');self.assertEqual(command[command.index('-b')+1],'256');self.assertEqual(command[command.index('-ub')+1],'128')
        self.assertTrue(all(body['cache_prompt'] for body in self.bodies))
        self.assertEqual(stats[1]['session_calls'],2);self.assertEqual(stats[0]['prompt_tokens'],1500);self.assertEqual(stats[0]['cached_tokens'],1200)

    def test_process_is_recycled_before_rss_limit_instead_of_killed(self):
        session=qwen_runtime.ModelSession()
        rss=[10]
        with patch('game.qwen_runtime.process_rss',side_effect=lambda pid:rss[0]):
            session.generate([{'role':'user','content':'a'}])
            rss[0]=qwen_runtime.RECYCLE_RSS+1
            stats={};session.generate([{'role':'user','content':'b'}],stats=stats)
        session.close()
        self.assertEqual(self.popen.call_count,2,'a fresh process before the next call');self.assertEqual(stats['recycled'],1)

    def test_one_shot_generate_keeps_original_behaviour(self):
        stats={}
        self.assertEqual(qwen_runtime.generate([{'role':'user','content':'a'}],stats=stats),{'ok':1})
        # Measured defaults (docs/paga-ai-benchmark.json): -t 6 -b 512 -ub 256, prompt cache on.
        self.assertEqual(self.popen.call_count,1);self.assertTrue(self.bodies[0]['cache_prompt'])
        command=self.popen.call_args[0][0];self.assertEqual(command[command.index('-t')+1],'6');self.assertEqual(command[command.index('-ub')+1],'256')

    def test_threads_are_bounded_and_low_memory_refuses_start(self):
        command=qwen_runtime.sandbox_command(1,'k',{'threads':64,'batch':64,'ubatch':32,'context':4096,'cache_prompt':False})
        self.assertEqual(command[command.index('-t')+1],'6')
        with patch('game.qwen_runtime.available_memory',return_value=1024**3),patch('game.qwen_runtime.MEMORY_WAIT_SECONDS',0):
            with self.assertRaises(MemoryError):qwen_runtime.ModelSession().generate([{'role':'user','content':'a'}])
        self.assertEqual(self.popen.call_count,0)

    def test_truncated_answer_is_never_executed(self):
        opener=qwen_runtime.urllib.request.build_opener()
        opener.open.side_effect=lambda request,timeout=None:FakeResponse(b'{}') if request.full_url.endswith('/health') else completion({'x':1},'length')
        with self.assertRaises(ValueError):qwen_runtime.generate([{'role':'user','content':'a'}])
