"""Pinned app-local CPU runtime; no OS package installs or system configuration changes."""
from pathlib import Path
import hashlib,json,os,subprocess,sys,tarfile,urllib.request
ROOT=Path(__file__).resolve().parents[1]
assert ROOT==Path('/home/oskar_zeus_admin/ZEUS_UAT')
DEST=ROOT/'runtime/qwen';DEST.mkdir(parents=True,exist_ok=True)
MODEL='Qwen3.5-4B-Q4_K_M.gguf';REV='e87f176479d0855a907a41277aca2f8ee7a09523';SHA='00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4'
COMMIT='cd959bae99ff4bed22bef2604f45241c09bbb8c8'
def fetch(url,path,sha=None):
    if path.exists() and (not sha or hashlib.file_digest(path.open('rb'),'sha256').hexdigest()==sha):return
    temporary=path.with_suffix(path.suffix+'.part');digest=hashlib.sha256();total=0
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'ZEUS-UAT-installer'}),timeout=120) as response,temporary.open('wb') as output:
        while chunk:=response.read(4*1024*1024):
            output.write(chunk);digest.update(chunk);total+=len(chunk)
            if total%(256*1024*1024)==0:print('Downloaded MB:',total//1048576,flush=True)
    if sha and digest.hexdigest()!=sha:temporary.unlink();raise RuntimeError('Checksum mismatch')
    temporary.replace(path)
fetch(f'https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/{REV}/{MODEL}',DEST/MODEL,SHA)
fetch(f'https://codeload.github.com/ggml-org/llama.cpp/tar.gz/{COMMIT}',DEST/'llama.cpp.tar.gz')
source=DEST/f'llama.cpp-{COMMIT}'
if not source.exists():
    with tarfile.open(DEST/'llama.cpp.tar.gz') as archive:archive.extractall(DEST,filter='data')
cmake=DEST/'tools/cmake/data/bin/cmake'
if not cmake.exists():subprocess.run([sys.executable,'-m','pip','install','--disable-pip-version-check','--no-warn-script-location','--target',str(DEST/'tools'),'cmake==3.31.6'],check=True)
subprocess.run([str(cmake),'-S',str(source),'-B',str(DEST/'build'),'-DCMAKE_BUILD_TYPE=Release','-DGGML_CUDA=OFF','-DGGML_NATIVE=ON','-DLLAMA_CURL=OFF','-DLLAMA_BUILD_TESTS=OFF','-DLLAMA_BUILD_EXAMPLES=ON'],check=True)
subprocess.run([str(cmake),'--build',str(DEST/'build'),'--target','llama-server','-j','2'],check=True)
(DEST/'MODEL.json').write_text(json.dumps({'id':'Qwen3.5-4B-Q4_K_M','upstream':'Qwen/Qwen3.5-4B','gguf':'unsloth/Qwen3.5-4B-GGUF','revision':REV,'sha256':SHA,'size':(DEST/MODEL).stat().st_size,'runtimeVersion':'v0.9.0','runtimeCommit':COMMIT},indent=2))
print('INSTALL COMPLETE: pinned weights verified; CPU runtime compiled.',flush=True)
