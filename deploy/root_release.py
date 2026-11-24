#!/opt/chess-ops/venv/bin/python -I
"""Root-owned zero-argument launcher with a fixed config and bounded JSON input."""
import json,os,re,subprocess,sys
from pathlib import Path

def validate(data):
 if not isinstance(data,dict) or set(data)!={'mode','image','commit'}:raise ValueError('Invalid promotion request')
 if data['mode'] not in ('stage','promote') or not isinstance(data['image'],str) or not isinstance(data['commit'],str):raise ValueError('Invalid request values')
 if not re.fullmatch(r'ghcr\.io/ali133-7/chess-ai-coach@sha256:[0-9a-f]{64}',data['image']) or not re.fullmatch('[0-9a-f]{40}',data['commit']):raise ValueError('Unapproved image or commit')
 return data
def main():
 if len(sys.argv)!=1 or os.geteuid()!=0:raise SystemExit('Root-owned launcher accepts no command-line arguments')
 raw=sys.stdin.buffer.read(2049)
 if len(raw)>2048:raise ValueError('Request too large')
 data=validate(json.loads(raw));config=Path('/etc/chess-private/release.json');script=Path('/opt/chess-ops/scripts/promote_release.py')
 for path in (config,script,Path(__file__)):
  info=path.stat()
  if path.is_symlink() or info.st_uid!=0 or info.st_mode&0o022:raise ValueError('Release tools and configuration must be root-owned and not group/world writable')
 subprocess.run([sys.executable,'-I',str(script),'--config',str(config),'--image',data['image'],'--commit',data['commit'],'--stage-only' if data['mode']=='stage' else '--execute'],check=True)
if __name__=='__main__':main()
