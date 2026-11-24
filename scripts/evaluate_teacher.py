"""No network by default. --live explicitly invokes the configured paid provider."""
import argparse,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio.teacher_v7 import evaluation

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--responses',type=Path);p.add_argument('--live',choices=['groq','grok','openrouter','openai'],action='append');p.add_argument('--max-cases',type=int,default=5);p.add_argument('--output',type=Path);p.add_argument('--pricing-file',type=Path)
 a=p.parse_args()
 if not 1<=a.max_cases<=64:p.error('--max-cases must be 1..64')
 if a.responses and a.live:p.error('Choose offline responses or live mode')
 validation=evaluation.validate()
 if validation['issues']:print(json.dumps(validation,ensure_ascii=False));return 1
 pricing=json.loads(a.pricing_file.read_text(encoding='utf8')) if a.pricing_file else None
 result={'runs':[evaluation.live(provider,a.max_cases,pricing) for provider in dict.fromkeys(a.live)]} if a.live else evaluation.compare([json.loads(line) for line in a.responses.read_text(encoding='utf8').splitlines() if line.strip()],pricing) if a.responses else validation
 text=json.dumps(result,ensure_ascii=False,indent=2)
 if a.output:
  # Evaluation files can include operational metadata; do not make them world-readable.
  fd=os.open(a.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
  with os.fdopen(fd,'w',encoding='utf8') as out:out.write(text)
 else:print(text)
 return 0
if __name__=='__main__':raise SystemExit(main())
