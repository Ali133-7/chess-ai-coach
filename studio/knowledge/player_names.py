"""Explicit spelling aliases; never infer titles or equate all players named Tal."""
import re,unicodedata

def words(value):
 text=''.join(c for c in unicodedata.normalize('NFKD',value.casefold()) if not unicodedata.combining(c))
 return tuple(re.findall(r'[^\W_]+',text,flags=re.UNICODE))

PLAYERS={
 'mikhail-tal':{
  'id':'mikhail-tal','name':'Mikhail Tal',
  'forms':('Mikhail Tal','Mihail Tal','ميخائيل تال','ميخايل تال'),
  'evidence':('https://museum.fide.com/champions/mikhail-tal','https://doi.org/10.6084/m9.figshare.4276523.v1'),
 }
}
KEYS={tuple(sorted(words(form))):p['id'] for p in PLAYERS.values() for form in p['forms']}
FORM_WORDS={key:tuple(frozenset(words(form)) for form in p['forms']) for key,p in PLAYERS.items()}

def resolve(query):
 key=KEYS.get(tuple(sorted(words(query))))
 return PLAYERS.get(key)

def matches(value,key):
 profile=PLAYERS.get(key)
 if not profile:return False
 actual=set(words(value))
 return any(form<=actual for form in FORM_WORDS[key])

def fts_query(profile):
 # Each conjunction is confined to one player's field. Opponent names and
 # opening/event text cannot jointly impersonate the requested player.
 return '('+' OR '.join(column+':('+' AND '.join('"'+w+'"' for w in words(form))+')' for column in ('white','black') for form in profile['forms'])+')'

def seed_filter(db,profile):
 db.create_function('chess_player_matches',2,matches,deterministic=True)
 return '(chess_player_matches(white,?) OR chess_player_matches(black,?))',(profile['id'],profile['id'])

def public(profile):
 return {'id':profile['id'],'name':profile['name'],'matched_spellings':list(profile['forms'])} if profile else None
