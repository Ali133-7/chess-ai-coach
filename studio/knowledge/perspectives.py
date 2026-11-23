"""Opening conventions are labels, not a claim that only one color can study a line."""
BLACK_GAMBITS=('Benko Gambit','Blumenfeld Countergambit','Elephant Gambit','Englund Gambit','Latvian Gambit','Duras Gambit')
WHITE_NAMES=("Queen's Pawn Game","King's Pawn Game",'Irish Gambit','English Orangutan','Yusupov-Rubinstein System','Creepy Crawly Formation','Formation','Italian Game','Ruy Lopez','London System','Vienna','Scotch Game',"King's Gambit","Queen's Gambit",'Blackmar-Diemer','Danish Gambit',"Bishop's Opening",'Four Knights','Center Game',"King's Indian Attack",'Nimzo-Larsen','Richter-Veresov','Torre Attack','Trompowsky','Rapport-Jobava','Colle System')

def orientation(name,family=None):
 family=family or name.split(':')[0]
 if any(family.startswith(x) for x in BLACK_GAMBITS):side='black';kind='countergambit'
 elif family.startswith(("Queen's Gambit Accepted","Queen's Gambit Declined")):side='both';kind='gambit-response'
 elif family.startswith(('Vienna','King\'s Indian Attack')):side='white';kind='initiative'
 elif family.endswith('Defense') or family.startswith(("Queen's Indian",'Semi-Slav','Slav Indian')):side='black';kind='defense'
 elif any(family.startswith(x) for x in WHITE_NAMES) or 'Opening' in family or family.endswith('Attack'):side='white';kind='initiative'
 else:side='both';kind='shared'
 return {'primary_side':side,'kind':kind,'basis':'opening-name convention; both sides remain available for study','white_label':{'ar':'نقلات الأبيض','en':'White moves'},'black_label':{'ar':'ردود الأسود','en':'Black replies'}}

def decorate(rows):
 from .traps import for_opening
 for row in rows:
  row['orientation']=orientation(row['name'],row.get('family'));row['trap_id']=for_opening(row['id'])
 return rows
