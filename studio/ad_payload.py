"""Bound JSON container depth before entering a native recursive decoder."""
import json,math

def validate_json(raw,max_depth=32):
 text=raw.decode('utf8');depth=0;quoted=False;escaped=False
 for char in text:
  if quoted:
   if escaped:escaped=False
   elif char=='\\':escaped=True
   elif char=='"':quoted=False
  elif char=='"':quoted=True
  elif char in '[{':
   depth+=1
   if depth>max_depth:raise ValueError('Advertising JSON nesting limit exceeded')
  elif char in ']}':depth-=1
 # The scanner only bounds structure; the standard decoder validates grammar.
 def reject_constant(_):raise ValueError('Non-finite advertising JSON value')
 value=json.loads(text,parse_constant=reject_constant);pending=[value]
 while pending:
  item=pending.pop()
  if isinstance(item,str):item.encode('utf8')
  elif isinstance(item,float) and not math.isfinite(item):raise ValueError('Non-finite advertising JSON number')
  elif isinstance(item,dict):
   for key,child in item.items():key.encode('utf8');pending.append(child)
  elif isinstance(item,list):pending.extend(item)
 return value
