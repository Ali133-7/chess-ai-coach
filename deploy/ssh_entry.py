#!/opt/chess-ops/venv/bin/python -I
"""Forced SSH command: accepts only `promote IMAGE_DIGEST COMMIT` or `stage ...`."""
import os,re,shlex,subprocess,json

def parse(command):
 parts=shlex.split(command)
 if len(parts)!=3 or parts[0] not in ('promote','stage'):raise ValueError('Unsupported release command')
 if not re.fullmatch(r'ghcr\.io/ali133-7/chess-ai-coach@sha256:[0-9a-f]{64}',parts[1]) or not re.fullmatch(r'[0-9a-f]{40}',parts[2]):raise ValueError('Unsupported release image or revision')
 return parts
if __name__=='__main__':
 mode,image,commit=parse(os.environ.get('SSH_ORIGINAL_COMMAND',''))
 subprocess.run(['/usr/bin/sudo','-n','/opt/chess-ops/root_release.py'],input=json.dumps({'mode':mode,'image':image,'commit':commit}),text=True,check=True)
