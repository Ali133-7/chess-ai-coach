"""Reproducible bilingual teacher checks. Lexical coverage is a proxy, not truth proof."""
import difflib,json,time,math
from collections import defaultdict
from pathlib import Path
import chess
from . import dialogue,grounding,providers
from .schema import TutorAnswer

CORPUS=Path(__file__).parent/'evaluation_cases.json'

def cases():return json.loads(CORPUS.read_text(encoding='utf8'))['cases']
def context(case):
 if case['intent']!='position':return {'scope':'general chess question; no inherited move','scenarios':[]}
 b=chess.Board(case.get('fen',chess.STARTING_FEN))
 for uci in case.get('prefix',[]):b.push_uci(uci)
 move=chess.Move.from_uci(case['move'])
 if move not in b.legal_moves:raise ValueError('Illegal corpus move: '+case['id'])
 facts={'capture':b.is_capture(move),'check':b.gives_check(move)};san=b.san(move);fen=b.fen();b.push(move);facts.update(checkmate=b.is_checkmate(),stalemate=b.is_stalemate())
 return {'fen':fen,'actual_move':{'uci':move.uci(),'san':san},'scenarios':[],'verified_move_facts':facts,'knowledge':{'documents':[],'scope':'Offline authored evaluation fixture; no user database retrieval'}}

def validate():
 data=cases();ids=set();issues=[]
 for case in data:
  if case['id'] in ids:issues.append({'id':case['id'],'error':'duplicate_id'})
  ids.add(case['id'])
  try:
   ctx=context(case)
   if dialogue.kind(case['question'])!=case['intent']:issues.append({'id':case['id'],'error':'intent_mismatch','actual':dialogue.kind(case['question'])})
   if case['intent']=='position' and not ctx.get('verified_move_facts'):raise ValueError('Missing legal facts')
  except (ValueError,KeyError) as exc:issues.append({'id':case.get('id'),'error':str(exc)})
 return {'cases':len(data),'languages':sorted({c['language'] for c in data}),'issues':issues,'authorship':'Original instructional fixtures; not historical games or user data.'}

def assess(case,answer):
 result={'case_id':case['id'],'language':case['language'],'topic':case['topic'],'schema_valid':False,'fact_check_passed':False,'concept_coverage':0.,'human_review':None}
 try:
  parsed=TutorAnswer.model_validate(answer);result['schema_valid']=True
  ctx=context(case);grounding.audit(parsed,ctx)
  if parsed.scenario_notes:raise ValueError('Corpus supplies no engine scenario IDs')
  result['fact_check_passed']=True
  text=dialogue.normalize(parsed.explanation_ar)
  groups=case.get('concept_groups',[])
  result['concept_coverage']=sum(any(dialogue.normalize(word) in text for word in group) for group in groups)/len(groups) if groups else None
 except (ValueError,providers.ProviderError):pass
 return result

def compare(responses,pricing=None):
 indexed={c['id']:c for c in cases()};rows=[];texts=[]
 for item in responses:
  if item['case_id'] not in indexed:raise ValueError('Unknown evaluation case')
  case=indexed[item['case_id']];row={**assess(case,item['answer']),'provider':item.get('provider','offline'),'model':item.get('model'),'latency_ms':item.get('latency_ms'),'input_tokens':item.get('input_tokens'),'output_tokens':item.get('output_tokens')}
  text=dialogue.normalize(item['answer'].get('explanation_ar',''))
  row['similar_unrelated_cases']=[other for other,lang,topic,prior in texts if lang==case['language'] and topic!=case['topic'] and len(text)>50 and difflib.SequenceMatcher(None,text,prior).ratio()>=.9]
  rate=(pricing or {}).get(row['provider'],{}).get(row['model'],{})
  row['estimated_cost_usd']=None
  if rate and row['input_tokens'] is not None and row['output_tokens'] is not None:
   values=[rate.get('input_per_million'),rate.get('output_per_million')]
   if rate.get('currency')!='USD' or not rate.get('as_of') or any(not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 for v in values):raise ValueError('Pricing requires dated nonnegative finite USD input/output rates per million tokens')
   row['estimated_cost_usd']=round((row['input_tokens']*values[0]+row['output_tokens']*values[1])/1000000,8);row['pricing_as_of']=rate['as_of']
  texts.append((case['id'],case['language'],case['topic'],text));rows.append(row)
 grouped=defaultdict(list)
 for row in rows:grouped[(row['provider'],row['model'])].append(row)
 summary=[]
 for (provider,model),items in grouped.items():
  latencies=sorted(r['latency_ms'] for r in items if isinstance(r['latency_ms'],(int,float)));coverage=[r['concept_coverage'] for r in items if r['concept_coverage'] is not None]
  known=[r['estimated_cost_usd'] for r in items if r['estimated_cost_usd'] is not None]
  summary.append({'provider':provider,'model':model,'cases':len(items),'schema_passes':sum(r['schema_valid'] for r in items),'narrow_fact_check_passes':sum(r['fact_check_passed'] for r in items),'mean_concept_proxy':sum(coverage)/len(coverage) if coverage else None,'p95_latency_ms':latencies[max(0,math.ceil(.95*len(latencies))-1)] if latencies else None,'similar_unrelated_answers':sum(bool(r['similar_unrelated_cases']) for r in items),'estimated_cost_usd':round(sum(known),8) if known else None,'cost_coverage_cases':len(known),'human_review':None})
 return {'results':rows,'summary':summary,'method':'Strict schema, actual local legal-move facts, narrow contradiction rules, required-concept substring groups, and >=0.90 text similarity across different topics in the same language. Coverage and similarity are review aids, not semantic truth or measured teaching effectiveness. Human review remains unset.','cost':'Token counts are provider-reported. Optional dated operator-supplied prices yield estimates, not invoices; absent prices remain null.'}

def live(provider,max_cases,pricing=None):
 from .service import provider_config,INSTRUCTIONS
 from ..locale import LANGUAGE
 cfg=provider_config()
 if provider not in cfg['providers']:raise ValueError('Provider not configured')
 cfg={**cfg,'primary':provider,'fallback':[]};responses=[]
 for case in cases()[:max_cases]:
  token=LANGUAGE.set(case['language']);started=time.perf_counter()
  try:
   ctx=context(case)
   answer,ins,outs,name,model=providers.generate(cfg,INSTRUCTIONS,{'VERIFIED_CONTEXT':ctx,'QUESTION_AR':case['question'],'RECENT_DISCUSSION':[]})
   responses.append({'case_id':case['id'],'answer':answer.model_dump(),'provider':name,'model':model,'latency_ms':round((time.perf_counter()-started)*1000,2),'input_tokens':ins,'output_tokens':outs})
  except providers.ProviderError:
   responses.append({'case_id':case['id'],'answer':{},'provider':provider,'model':cfg['providers'][provider]['model'],'latency_ms':round((time.perf_counter()-started)*1000,2)})
  finally:LANGUAGE.reset(token)
 return compare(responses,pricing)
