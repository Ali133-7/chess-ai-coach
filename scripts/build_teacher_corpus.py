"""Author-owned bilingual instructional fixtures; never labelled as real player games."""
import json
from pathlib import Path

def build():
 positions=[
  ('central-development',[],None,'e2e4', [['مركز','وسط']], [['center','centre']]),
  ('knight-development',['e2e4','e7e5'],None,'g1f3',[['حصان'],['تطوير','تطور']],[['knight'],['develop']]),
  ('central-capture',['e2e4','e7e5','g1f3','b8c6','d2d4'],None,'e5d4',[['بيدق'],['اسر','اخذ','تبادل']],[['pawn'],['capture','take','exchange']]),
  ('fools-mate',['f2f3','e7e5','g2g4'],None,'d8h4',[['مات']],[['mate']]),
  ('scholars-mate',['e2e4','e7e5','f1c4','b8c6','d1h5','g8f6'],None,'h5f7',[['مات'],['وزير','ملكة']],[['mate'],['queen']]),
  ('castling',['e2e4','e7e5','g1f3','b8c6','f1c4','g8f6'],None,'e1g1',[['تبييت'],['ملك']],[['castl'],['king']]),
  ('en-passant',['e2e4','a7a6','e4e5','d7d5'],None,'e5d6',[['تجاوز','مرور'],['بيدق']],[['passant'],['pawn']]),
  ('stalemate',[],'7k/5K2/8/6Q1/8/8/8/8 w - - 0 1','g5g6',[['تعادل','بات']],[['stalemate','draw']]),
 ]
 general=[
  ('identity','identity',['من أنت؟','هل أنت إنسان؟'],['Who are you?','What are you?'],[['معلم','مساعد']], [['assistant','teacher']]),
  ('greeting','greeting',['مرحبا','السلام عليكم'],['Hello','Good morning'],[],[]),
  ('italian','general',['بشكل عام ما فكرة الافتتاح الإيطالي؟','بشكل عام كيف أتعلم الافتتاح الإيطالي؟'],['What is the idea of the Italian opening?','How can I study the Italian opening?'],[['تطوير','تطور']],[['develop']]),
  ('king-safety','general',['بشكل عام كيف أحمي الملك؟','بشكل عام لماذا نهتم بأمان الملك؟'],['How do I protect my king in general?','Why is king safety important?'],[['ملك']],[['king']]),
  ('fork-definition','general',['بشكل عام ما الشوكة في الشطرنج؟','بشكل عام كيف أفهم تكتيك الشوكة؟'],['What is a fork in chess?','How does a chess fork work?'],[['قطعتين','هدفين','اكثر من']],[['two','multiple','simultaneous']]),
  ('endgames','general',['بشكل عام كيف أدرس نهايات البيادق؟','بشكل عام ما أهمية نشاط الملك في النهاية؟'],['How should I study pawn endings?','Why is king activity important in endgames?'],[['ملك'],['بيدق','بيادق']],[['king'],['pawn']]),
  ('opening-principles','general',['بشكل عام ما مبادئ الافتتاح؟','بشكل عام كيف أبدأ مباراة شطرنج؟'],['What are opening principles?','How should I begin a chess game?'],[['مركز','وسط'],['تطوير','تطور']],[['center','centre'],['develop']]),
  ('pinned-piece','general',['بشكل عام ما تثبيت القطعة؟','بشكل عام كيف أتعرف على الربط؟'],['What is a pinned piece?','How do I recognize a pin in chess?'],[['ملك','قطعة','قيم']],[['king','piece','valuable']]),
 ]
 cases=[]
 for topic,prefix,fen,move,ar,en in positions:
  questions={'ar':['اشرح هذه النقلة وفائدتها ومخاطرها.','لماذا هذه النقلة مهمة في هذه الوضعية؟'],'en':['Explain this move, its benefit and its risks.','Why is this move important in this position?']}
  for lang,groups in [('ar',ar),('en',en)]:
   for i,q in enumerate(questions[lang]):
    cases.append({'id':f'{topic}-{lang}-{i+1}','topic':topic,'language':lang,'intent':'position','question':q,'prefix':prefix,'move':move,'concept_groups':groups,**({'fen':fen} if fen else {})})
 for topic,intent,arq,enq,ar,en in general:
  for lang,questions,groups in [('ar',arq,ar),('en',enq,en)]:
   for i,q in enumerate(questions):cases.append({'id':f'{topic}-{lang}-{i+1}','topic':topic,'language':lang,'intent':intent,'question':q,'concept_groups':groups})
 return {'version':1,'license':'Original project instructional fixtures','authorship':'Manually specified legal sequences and original bilingual questions; generated IDs enumerate paraphrases, not independent historical games. Expected chess facts are recomputed with python-chess. Lexical concept labels require human review for teaching quality.','cases':cases}

if __name__=='__main__':
 dest=Path(__file__).resolve().parents[1]/'studio/teacher_v7/evaluation_cases.json'
 dest.write_text(json.dumps(build(),ensure_ascii=False,indent=2)+'\n',encoding='utf8')
 print('WROTE',len(build()['cases']),'authored bilingual cases')
