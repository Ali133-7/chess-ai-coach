"""Bounded local retrieval and explicit, limited contradiction checks. No web calls."""
import copy,hashlib,json,re,sqlite3
from functools import lru_cache
import chess
from .providers import ProviderError

def words(text):return set(re.findall(r'[\w]+',str(text).lower()))-{'the','and','what','this','كيف','لماذا','هذا','هذه','على','في','من'}

@lru_cache(maxsize=1)
def lessons():
 from ..knowledge.curriculum import data
 d=data();result=[]
 for x in d['lessons']:
  text=' '.join(x['theory'].get('en',[])+x['theory'].get('ar',[]))
  result.append({'id':'lesson:'+x['id'],'title':x['title'],'text':text[:1800],'revision':d['revision'],'source':'Local original curriculum','license':'Original project material','tokens':words(text+json.dumps(x['title'],ensure_ascii=False))})
 return result

def retrieve(question,fen=None):
 documents=[];q=words(question)
 try:
  from ..knowledge import store
  from ..knowledge.recognition import position_key
  with store.connection() as db:
   if fen:
    key=position_key(chess.Board(fen))
    rows=db.execute('SELECT DISTINCT o.id,o.eco,o.name,o.pgn,o.revision FROM kc_openings o JOIN kc_paths p ON p.revision=o.revision AND p.opening_id=o.id WHERE p.position_key=? OR p.before_key=? ORDER BY o.plies,o.id LIMIT 3',(key,key)).fetchall()
   else:
    terms=sorted(q,key=lambda t:(-len(t),t))[:4];rows=[]
    for term in terms:
     if len(term)<3:continue
     rows.extend(db.execute('SELECT id,eco,name,pgn,revision FROM kc_openings WHERE name LIKE ? LIMIT 2',('%'+term+'%',)).fetchall())
   seen=set()
   for row in rows:
    if row['id'] in seen:continue
    seen.add(row['id']);documents.append({'id':'opening:'+row['id'],'title':row['eco']+' '+row['name'],'text':row['pgn'][:700],'revision':row['revision'],'source':'https://github.com/lichess-org/chess-openings','license':'CC0-1.0'})
    if len(documents)>=3:break
 except (sqlite3.Error,OSError,ValueError):pass
 ranked=sorted(((len(q & x['tokens']),x['id'],x) for x in lessons()),key=lambda item:(-item[0],item[1]))
 for score,_,doc in ranked[:3]:
  if score:documents.append({k:v for k,v in doc.items() if k!='tokens'})
 return {'documents':documents[:6],'retrieval':'Exact local position match plus deterministic token overlap; no embedding confidence score.','scope':'Reference facts are not evidence that a continuation is forced.'}

def enrich(context,question):
 out=copy.deepcopy(context);out['knowledge']=retrieve(question,context.get('fen'))
 if context.get('fen') and context.get('actual_move',{}).get('uci'):
  b=chess.Board(context['fen']);m=chess.Move.from_uci(context['actual_move']['uci'])
  if m not in b.legal_moves:raise ValueError('Illegal supplied move')
  capture=b.is_capture(m);check=b.gives_check(m);b.push(m)
  out['verified_move_facts']={'capture':capture,'check':check,'checkmate':b.is_checkmate(),'stalemate':b.is_stalemate()}
 return out

def audit(answer,context):
 # Only unambiguous assertions about THIS move are checked. This cannot prove
 # arbitrary natural-language chess analysis and must never be labelled as such.
 text=answer.explanation_ar.lower();facts=context.get('verified_move_facts',{})
 patterns={'checkmate':r'(?:this move (?:is|delivers) checkmate|هذه النقلة (?:هي|تحقق) كش مات)',
           'capture':r'(?:this move captures a piece|هذه النقلة تأسر قطعة)',
           'check':r'(?:this move gives check|هذه النقلة تعطي كش)'}
 violations=[name for name,pattern in patterns.items() if facts.get(name) is False and re.search(pattern,text)]
 if violations:raise ProviderError('Explanation contradicts verified move facts','invalid_output')
 docs=context.get('knowledge',{}).get('documents',[])
 return {'sources':[{k:v for k,v in d.items() if k!='text'} for d in docs],
         'grounding':{'facts':facts,'checks':'scenario IDs and legal board actions; narrow explicit check/capture/mate assertions','prose_formally_verified':False,'retrieved_documents':len(docs)}}
