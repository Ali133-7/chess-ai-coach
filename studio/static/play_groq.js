'use strict';
(()=>{
 const P={game:null,busy:false,selected:null,flip:false,loadedFor:null,poll:null,preview:null,
  coach:null,coachPly:0,coachBusy:false,coachError:'',coachSeq:0,cache:new Map()};
 const el=id=>document.getElementById(id);
 const note=(text,error=false)=>{el('groq-play-status').textContent=text;el('groq-play-status').classList.toggle('error',error);};
 const teaching=()=>el('training-teaching').checked;
 const owner=()=>S.me?.id;
 function clearCoach(){P.coachSeq++;P.coach=null;P.coachPly=0;P.coachBusy=false;P.coachError='';P.preview=null;P.cache.clear();}
 function defaultPly(){
  const g=P.game;if(!g?.moves.length)return 0;
  for(let i=g.moves.length-1;i>=0;i--)if((i%2===0)===(g.player_color==='white'))return i+1;
  return g.moves.length;
 }
 function renderCoach(){
  const a=P.coach,on=teaching();el('training-coach-body').hidden=!on;
  el('training-coach-empty').hidden=!!a;el('training-coach-content').hidden=!a;
  el('training-coach-status').textContent=P.coachBusy?(a?'جارٍ إعداد الشرح الموسّع…':'المعلّم يحلل النقلة…'):P.coachError;
  el('training-coach-status').classList.toggle('error',!!P.coachError);
  if(!a)return;
  el('training-coach-title').textContent=(a.mover_is_you?'نقلتك':'نقلة الخصم')+' · '+a.san;
  const badge=el('training-grade');badge.textContent=a.grade_ar;badge.dataset.grade=a.grade;
  el('training-evaluation').textContent=a.evaluation_ar;el('training-eval-bar').value=Math.max(0,Math.min(100,Number(a.advantage_percent)||0));
  el('training-summary').textContent=a.summary_ar;
  const list=(id,items)=>{const target=el(id);target.replaceChildren();for(const text of items){const li=document.createElement('li');li.textContent=text;target.append(li);}};
  list('training-benefits',a.benefits_ar||[]);list('training-risks',a.risks_ar||[]);
  el('training-best').textContent=a.best_played?'لعبت الخيار الأول للمحرك':'البديل المفضل: '+a.best_san;
  el('training-preview').hidden=!a.scenarios?.length;
  el('training-deeper').disabled=P.coachBusy;el('training-question-send').disabled=P.coachBusy;el('training-question').disabled=P.coachBusy;
  el('training-explanation').hidden=!a.explanation;
  el('training-explanation-text').textContent=a.explanation?.explanation_ar||'';
  el('training-learning-question').textContent=a.explanation?.learning_question_ar||'';
  el('training-explanation-note').textContent=a.explanation_error||'';
 }
 function render(){
  const g=P.game;el('groq-play-empty').hidden=!!g;el('groq-play-game').hidden=!g;
  el('groq-new').disabled=P.busy;el('groq-color').disabled=P.busy;el('groq-level').disabled=P.busy;
  if(!g)return;
  window.updatePlayOpening?.(g);
  const preview=P.preview,legal=P.busy||preview?[]:g.legal_moves;
  const targets=P.selected?legal.filter(m=>m.startsWith(P.selected)).map(m=>m.slice(2,4)):[];
  const last=preview?(preview.step?preview.line.moves[preview.step-1]:null):g.last_move;
  window.ChessBoardPro.render(el('groq-board'),preview?preview.line.fens[preview.step]:g.fen,P.flip?(g.player_color==='white'?'black':'white'):g.player_color,{
   selected:P.selected,targets,legalMoves:legal,last:last?[last.slice(0,2),last.slice(2,4)]:[],lastUci:last,
   hintArrow:preview?preview.line.moves[preview.step]||null:null,onMove:drop,onClick:click});
  el('groq-player-label').textContent='أنت · '+(g.player_color==='white'?'الأبيض':'الأسود');
  el('groq-opponent-label').textContent='Stockfish · '+(g.level_ar||'قوي');
  el('groq-turn').textContent=P.busy?'المحرك يفكر…':g.message;
  el('groq-turn').classList.toggle('is-thinking',P.busy||g.state==='thinking');
  el('groq-retry').hidden=g.state!=='ai_turn'||P.busy;
  el('groq-resign').disabled=P.busy||g.state==='finished';
  el('groq-moves').innerHTML=g.moves.length?g.moves.map((m,i)=>`<button type="button" class="${P.coachPly===i+1?'active':''}" data-coach-ply="${i+1}" aria-label="شرح النقلة ${i+1}: ${esc(m.san)}">${i%2===0?`<b>${Math.floor(i/2)+1}.</b> `:''}${esc(m.san)}</button>`).join(''):'<p class="muted">ستظهر النقلات هنا. اضغط نقلة لشرحها.</p>';
  el('groq-result').hidden=!g.result;el('groq-result').textContent=g.result?'النتيجة: '+g.result:'';
  el('training-preview-controls').hidden=!preview;
  if(preview){el('training-preview-note').textContent=`معاينة البديل من النقلة ${preview.ply} · ${preview.step}/${preview.line.moves.length}`;el('training-preview-prev').disabled=preview.step===0;el('training-preview-next').disabled=preview.step>=preview.line.moves.length;}
  renderCoach();
 }
 async function coach(ply,elaborate=false,question=''){
  if(!P.game||!ply||!teaching())return;
  const gid=P.game.id,uid=owner(),seq=++P.coachSeq,key=gid+':'+ply+':'+(window.I18n?.lang||'ar');
  P.coachPly=ply;P.coach=P.cache.get(key)||null;P.coachError='';
  if(P.preview&&P.preview.ply!==ply)P.preview=null;
  if(P.coach&&!elaborate){P.coachBusy=false;render();return;}
  P.coachBusy=true;render();
  try{
   const result=await request('/play/games/'+gid+'/coach',{method:'POST',body:{ply,elaborate,question}});
   if(seq!==P.coachSeq||P.game?.id!==gid||owner()!==uid)return;
   P.coach=result;P.cache.set(key,result);
   if(result.explanation_error)el('training-explanation-note').textContent=result.explanation_error;
  }catch(err){if(seq===P.coachSeq&&owner()===uid)P.coachError=err.message;}
  finally{if(seq===P.coachSeq&&owner()===uid){P.coachBusy=false;render();}}
 }
 async function sync(){
  if(!P.game)return;const id=P.game.id,uid=owner();const g=await request('/play/games/'+id);
  if(owner()!==uid||P.game?.id!==id)return;P.game=g;P.selected=null;render();
 }
 async function ai(teachAfter=true){
  if(P.busy||!P.game||P.game.state!=='ai_turn')return;
  const id=P.game.id,uid=owner();P.busy=true;P.selected=null;note('المحرك يختار نقلته…');render();
  try{
   const game=await request('/play/games/'+id+'/ai',{method:'POST',body:{version:P.game.version}});
   if(P.game?.id===id&&owner()===uid){P.game=game;note(game.message);if(teachAfter&&!P.coachPly)coach(defaultPly());}
  }catch(err){if(owner()===uid){note(err.message,true);try{await sync();}catch{}}}
  finally{if(owner()===uid){P.busy=false;render();}}
 }
 function click(square){
  const g=P.game;if(P.busy||P.preview||g?.state!=='your_turn')return;
  if(P.selected&&g.legal_moves.some(m=>m.startsWith(P.selected+square))){drop(P.selected,square);return;}
  P.selected=g.legal_moves.some(m=>m.startsWith(square))?square:null;render();
 }
 function drop(from,to){
  const g=P.game;if(P.busy||P.preview||g?.state!=='your_turn')return;
  const moves=g.legal_moves.filter(m=>m.startsWith(from+to));if(!moves.length)return;
  window.ChessBoardPro.promotion(moves,move);
 }
 async function move(uci){
  if(P.busy||!P.game||P.preview)return;
  const gid=P.game.id,uid=owner();let movedPly=0;P.busy=true;P.selected=null;render();
  try{
   const game=await request('/play/games/'+gid+'/move',{method:'POST',body:{uci,version:P.game.version}});
   if(owner()!==uid||P.game?.id!==gid)return;
   P.game=game;note(game.message);movedPly=game.moves.length;P.coachSeq++;P.coachPly=movedPly;P.coach=null;P.coachBusy=false;P.coachError='';
  }catch(err){if(owner()===uid){note(err.message,true);try{await sync();}catch{}}}
  finally{if(owner()===uid){P.busy=false;render();}}
  if(owner()===uid&&P.game?.id===gid&&P.game.state==='ai_turn')await ai(false);
  if(movedPly&&owner()===uid&&P.game?.id===gid)coach(movedPly);
 }
 async function load(){
  if(!S.me)return;const uid=owner();
  if(P.loadedFor!==uid){P.game=null;P.loadedFor=uid;P.selected=null;P.busy=false;clearCoach();}
  try{
   const status=await request('/play/status');if(owner()!==uid)return;
   el('groq-availability').textContent=status.ready?'المحرك جاهز':'يحتاج تشغيل Stockfish';el('groq-new').disabled=!status.ready;
   const data=await request('/play/current');if(owner()!==uid)return;
   if(P.game?.id!==data.game?.id)clearCoach();P.game=data.game;render();el('groq-new').disabled=!status.ready||P.busy;
   if(P.game?.moves.length)coach(P.coachPly||defaultPly());
   if(P.game?.state==='ai_turn')await ai();
   else if(P.game?.state==='thinking'){
    note('هناك نقلة قيد التفكير. سنحدّث الرقعة تلقائياً.');clearTimeout(P.poll);P.poll=setTimeout(()=>{if(S.view==='play'&&!P.busy)load();},2500);
   }else note(P.game?P.game.message:'اختر لونك ومستوى الخصم وابدأ.');
  }catch(err){if(owner()===uid)note(err.message,true);}
 }
 document.addEventListener('languagechange',()=>{P.cache.clear();P.coach=null;P.coachSeq++;P.coachBusy=false;if(P.game)render();});
 window.loadGroqPlay=load;
 el('groq-new').addEventListener('click',async()=>{
  if(P.busy)return;if(P.game?.status==='active'&&P.game.moves.length&&!confirm('بدء مباراة جديدة بدلاً من المباراة الحالية؟'))return;
  const uid=owner();P.busy=true;note('جارٍ تجهيز الرقعة…');render();
  try{
   const game=await request('/play/games',{method:'POST',body:{color:el('groq-color').value,level:el('groq-level').value}});
   if(owner()!==uid)return;P.game=game;P.flip=false;P.selected=null;clearCoach();note(game.message);
  }catch(err){if(owner()===uid)note(err.message,true);}
  finally{if(owner()===uid){P.busy=false;render();}}
  if(owner()===uid&&P.game?.state==='ai_turn')await ai();
 });
 el('groq-retry').addEventListener('click',ai);
 el('groq-flip').addEventListener('click',()=>{P.flip=!P.flip;render();});
 el('groq-resign').addEventListener('click',async()=>{
  if(P.busy||!P.game||!confirm('هل تريد إنهاء هذه المباراة بالاستسلام؟'))return;
  const uid=owner(),id=P.game.id;
  try{const game=await request('/play/games/'+id+'/resign',{method:'POST',body:{version:P.game.version}});if(owner()!==uid||P.game?.id!==id)return;P.game=game;note(game.message);render();}catch(err){if(owner()===uid)note(err.message,true);}
 });
 el('groq-moves').addEventListener('click',e=>{const b=e.target.closest('[data-coach-ply]');if(b){el('training-teaching').checked=true;coach(Number(b.dataset.coachPly));}});
 el('training-teaching').addEventListener('change',()=>{if(teaching())coach(P.coachPly||defaultPly());else{P.coachSeq++;P.coachBusy=false;P.preview=null;render();}});
 el('training-deeper').addEventListener('click',()=>coach(P.coachPly,true));
 el('training-question-form').addEventListener('submit',e=>{e.preventDefault();if(P.coachBusy)return;const q=el('training-question').value.trim();if(q){coach(P.coachPly,true,q);el('training-question').value='';}});
 el('training-preview').addEventListener('click',()=>{const line=P.coach?.scenarios?.[0];if(!line?.fens?.length)return;P.preview={line,step:0,ply:P.coach.ply};P.selected=null;render();el('groq-board').scrollIntoView({block:'nearest',behavior:'smooth'});});
 el('training-preview-prev').addEventListener('click',()=>{if(P.preview?.step>0){P.preview.step--;render();}});
 el('training-preview-next').addEventListener('click',()=>{if(P.preview&&P.preview.step<P.preview.line.moves.length){P.preview.step++;render();}});
 el('training-preview-close').addEventListener('click',()=>{P.preview=null;render();});
 document.addEventListener('visibilitychange',()=>{if(!document.hidden&&S.view==='play'&&!P.busy)load();});
})();
