import os,subprocess,sys
from pathlib import Path
root=Path.cwd()
vs=Path(r"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat")
command='""'+str(vs)+'" -no_logo -arch=x64 && set"'
result=subprocess.run('cmd.exe /d /s /c '+command,capture_output=True,text=True,errors='replace',check=True)
for line in result.stdout.splitlines():
 if '=' in line:
  key,value=line.split('=',1)
  if key: os.environ[key]=value
os.environ['PATH']=r'C:\Users\xiedc\.cargo\bin;'+os.environ['PATH']

os.environ['RUSTUP_TOOLCHAIN']='1.94.0'
os.environ['CARGO_HOME']=str(root/'.pytest_cache/native-determinism-p0/backend-cargo')
source=root/'.pytest_cache/native-determinism-p0/backend/maturin-1.13.1'
with (root/'.pytest_cache/native-determinism-p0/backend-build.log').open('w',encoding='utf8') as log:
 for args in [['cargo','fetch','--locked'],['cargo','build','--release','--locked','--offline']]:
  r=subprocess.run(args,cwd=source,stdout=log,stderr=log)
  log.flush()
  if r.returncode: raise SystemExit(r.returncode)
