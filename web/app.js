/* Chess AI Coach Pro — private, dependency-free browser frontend.
   No localStorage, sessionStorage, cookies or telemetry: API key is kept only in memory.
   This page accesses ONLY completed Chess.com games and isolated local practice. */
'use strict';
const $ = id => document.getElementById(id);
const state = {key:'', view:'dashboard', dashboard:null, games:[], gamePage:1, gameTotal:0,
  review:null, reviewPly:0, reviewFlip:false, puzzles:[], puzzleIndex:0, puzzleSelect:null,
  puzzleResult:null, puzzleReveal:false, puzzleHint:null,puzzleContinuation:null,
  session:null, trainSelect:null, trainFlip:false,trainHint:null,
  busy:false, insightPlan:null, reviewExplore:false, reviewTrial:null, reviewLineMoves:[], reviewSelect:null, scenarioMode:null};
const PIECE = {K:'♔',Q:'♕',R:'♖',B:'♗',N:'♘',P:'♙',k:'♚',q:'♛',r:'♜',b:'♝',n:'♞',p:'♟\uFE0E'};
const VIEW_TITLES = {dashboard:'لوحة القيادة',games:'مراجعة مبارياتي',puzzles:'تحديات أخطائي',training:'العب ضد المحرك',insights:'تحليل المستوى',issues:'سجل الأخطاء',plan:'الخطة الأسبوعية'};
const QUALITIES = {'هفوة كبيرة':'هفوة كبيرة','خطأ':'خطأ','عدم دقة':'عدم دقة','جيدة':'جيدة'};
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function dateFmt(s){try{return new Date(typeof s==='number'?s*1000:s).toLocaleDateString('ar-IQ',{year:'numeric',month:'short',day:'numeric'});}catch{return '—';}}
function notify(message,timeout=3500){const el=$('toast');el.textContent=message;el.classList.add('show');clearTimeout(notify.timer);notify.timer=setTimeout(()=>el.classList.remove('show'),timeout);}
async function api(path,{method='GET',body}={}){
  if(!state.key)throw new Error('ادخل مفتاح الوصول أولاً.');
  const response=await fetch(path,{method,cache:'no-store',headers:{'X-API-Key':state.key,...(body?{'Content-Type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{})});
  if(!response.ok){const detail=await response.json().catch(()=>({}));if(response.status===401){state.key='';$('app-content').hidden=true;$('connection').hidden=false;$('server-status').textContent='انتهت جلسة الاتصال';}throw new Error(response.status===401?'مفتاح API غير صحيح':(detail.detail||'فشل الاتصال بالخادم')+' ('+response.status+')');}
  return response.json();
}
function busy(button,on,label){if(!button)return;if(on){button.dataset.original=button.textContent;button.textContent=label||'جارٍ التحميل...';button.disabled=true;}else{button.textContent=button.dataset.original||button.textContent;button.disabled=false;}}
function setView(view){if(!VIEW_TITLES[view])return;state.view=view;for(const node of document.querySelectorAll('.view'))node.hidden=node.id!=='view-'+view;
  for(const node of document.querySelectorAll('[data-view]'))node.classList.toggle('active',node.dataset.view===view);
  $('page-heading').textContent=VIEW_TITLES[view];document.querySelector('.sidebar').classList.remove('open');
  history.replaceState(null,'','#'+view);window.scrollTo({top:0,behavior:'smooth'});
  if(view==='dashboard'){loadDashboard();refreshDeepStatus();}if(view==='games')loadGames(true);if(view==='puzzles')loadPuzzles();if(view==='training')drawTraining();if(view==='insights'){loadInsights();window.CoachAdvanced?.progress();}if(view==='issues')window.CoachAdvanced?.issues();if(view==='plan')loadPlan();
}
function parseFen(fen){const ranks=fen.split(' ')[0].split('/');const obj={};if(ranks.length!==8)return obj;for(let r=0;r<8;r++){let f=0;for(const ch of ranks[r]){if(/^[1-8]$/.test(ch)){f+=Number(ch);}else{obj['abcdefgh'[f]+(8-r)]=ch;f++;}}}return obj;}
function drawBoard(el,fen,orientation='white',options={}){
  window.ChessBoardPro.render(el,fen,orientation,options);
}
function chooseMove(moves,callback){window.ChessBoardPro.promotion(moves,callback);}
function stat(icon,value,label){return `<article class="stat-card"><div class="stat-icon">${icon}</div><div class="stat-value">${esc(value)}</div><div class="stat-label">${esc(label)}</div></article>`;}
function formatGame(g){const opponent=(g.white||'').toLowerCase()===(state.dashboard?.username||'ali_ebrahim').toLowerCase()?g.black:g.white;
  const text={win:'فوز',loss:'خسارة',draw:'تعادل'}[g.result]||'غير معروف';return `<button class="game-entry" data-game="${esc(g.id)}"><div><span class="opponent">♟ ${esc(opponent)}</span><small>${esc(dateFmt(g.finished_at))} · ${esc(g.opening||'')} ${g.analyzed?'· تحليل جاهز':''}</small></div><span class="result-badge ${esc(g.result)}">${esc(text)}</span></button>`;}
async function loadDashboard(){if(!state.key)return;try{const d=await api('/api/pro/dashboard');state.dashboard=d;
  const rate=d.games?Math.round((d.wins/d.games)*100):0;
  $('stat-cards').innerHTML=stat('♟',d.games,'مباراة في الأرشيف')+stat('🏆',rate+'%','نسبة الفوز')+stat('◈',d.puzzles_available,'تمرين من أخطائك')+stat('♙',d.puzzles_due,'تدريب مستحق الآن');
  $('dashboard-games').innerHTML=d.recent.length?d.recent.slice(0,5).map(formatGame).join(''):'<div class="empty">بعد المزامنة ستظهر مبارياتك هنا.</div>';
  const phase=d.weak_phases[0];$('focus-card').innerHTML=phase?`<div class="focus-block"><div class="focus-emoji">◎</div><div><strong>${esc(phase.phase)}</strong><small>${esc(phase.errors)} ملاحظات تحتاج تدريباً</small></div></div><p class="muted">${esc(phase.tip)}</p><div class="notice">راجع التحديات المستحقة وتدرّب 20 دقيقة يومياً.</div>`:'<div class="empty">العب مباريات أكثر وسنستخرج أهم نقاط التحسين.</div>';
  $('server-status').textContent='متصل · '+d.analyzed+' مباراة محللة';$('server-status').previousElementSibling?.classList.add('online');
}catch(e){notify('تعذر تحميل الإحصائيات: '+e.message);}}
async function loadGames(reset=false){if(!state.key)return;try{if(reset){state.gamePage=1;state.games=[];}const page=state.gamePage;
  const d=await api('/api/pro/games?limit=30&page='+page);state.gameTotal=d.total;state.games.push(...d.games);
  $('games-total').textContent=state.gameTotal+' مباراة';$('games-list').innerHTML=state.games.length?state.games.map(formatGame).join(''):'<div class="empty">لا توجد مباريات مخزنة. استخدم زر تحديث المباريات.</div>';
  $('load-more-games').hidden=state.games.length>=state.gameTotal;
}catch(e){notify(e.message);}}
function showReviewAdvice(ply){const el=$('review-advice'),item=state.review?.plies[ply];if(!item||!item.lesson){el.innerHTML=`<div class="advice-placeholder"><span class="big-icon">♟</span>${ply?'هذه النقلة ليست من نقلات اللاعب التي قيّمها المحرك، أو لم تُرصد كملاحظة.':'اختر نقلة من قائمتك، واستعرض شرحها هنا.'}</div>`;return;}
  const l=item.lesson,quality=l.quality||'جيدة',same=l.played===l.best;el.innerHTML=`<span class="pill">${esc(quality)} · ${esc(l.concept||'تحليل')}</span><div class="advice-title">${esc(item.move_number)}${item.played_by==='white'?'.':'...'} ${esc(l.played)}</div><p class="advice-body">${esc(l.coaching?.text||l.explanation_ar||'')}</p>${l.coaching?.best_reason?`<p class="review-tip"><strong>الفكرة في هذا الموقف:</strong> ${esc(l.coaching.best_reason)}</p>`:''}<div class="best-move"><span>اقتراح Stockfish</span><strong>${esc(l.best||'—')}</strong></div><div class="review-tip">${esc(l.concept_tip||'')}</div><p class="tiny muted">${same?'مطابقة مع النقلة الأولى للمحرك.':'مقارنة تقريبية بزمن تحليل محدود؛ أعد التحليل لدقة أفضل.'}</p>`;
}
function drawReview(){const r=state.review;if(!r)return;const ply=Math.max(0,Math.min(state.reviewPly,r.total_plies));state.reviewPly=ply;
  const entry=r.plies[ply], variant=state.reviewExplore?state.reviewTrial:null;
  const last=variant?state.reviewLineMoves.at(-1):entry?.uci;
  const grade=variant?null:(entry?.quality_code||entry?.lesson?.quality_code||entry?.quality||entry?.lesson?.quality);
  const legal=state.reviewExplore?(variant?.legal_moves||entry?.legal_moves||[]):[];
  const dest=state.reviewSelect?legal.filter(x=>x.startsWith(state.reviewSelect)).map(x=>x.slice(2,4)):[];
  drawBoard($('review-board'),variant?.fen||entry.fen,state.reviewFlip?(r.player_color==='white'?'black':'white'):r.player_color,
    {last:last?[last.slice(0,2),last.slice(2,4)]:[], lastUci:last,
     quality:grade?{code:grade,uci:last}:null,legalMoves:legal,
     selected:state.reviewSelect,targets:dest,onClick:reviewClick,onMove:reviewDrop});
  if($('review-variation-status'))$('review-variation-status').textContent=state.reviewExplore?
    ('تجربة حرة · '+state.reviewLineMoves.length+' نقلة. حرّك القطع بالسحب أو النقر، والتقييم المحفوظ يخص المباراة الأصلية.'):
    'فعّل تجربة النقلات لتحريك قطع هذا الموقف بعد انتهاء المباراة.';
  $('review-range').max=String(r.total_plies);$('review-range').value=String(ply);
  $('review-counter').textContent=ply===0?'بداية المباراة':`نقلة ${r.plies[ply].move_number}${r.plies[ply].played_by==='white'?'.':'...'} ${r.plies[ply].san} · ${ply} / ${r.total_plies}`;
  const list=$('review-moves');
  if(list.dataset.renderedPly!==String(ply)||list.dataset.renderedGame!==r.id){
   list.innerHTML=r.plies.slice(1).map(p=>`<button class="move-tag ${p.ply===ply?'active':''} ${p.quality==='هفوة كبيرة'||p.quality==='خطأ'?'error':p.quality==='عدم دقة'?'imprecise':''}" data-ply="${p.ply}">${p.move_number}${p.played_by==='white'?'.':'...'} ${esc(p.san)} ${window.MoveGrade.html(p.quality_code||p.quality||p.lesson?.quality_code)}</button>`).join('');
   list.dataset.renderedPly=String(ply);list.dataset.renderedGame=r.id;
   const active=list.querySelector('.active');if(active)active.scrollIntoView({block:'nearest',inline:'nearest'});
   showReviewAdvice(ply);window.CoachAdvanced?.reviewPly(r,ply);
  }
}
async function openGame(gid){try{const r=await api('/api/pro/review/'+encodeURIComponent(gid));state.review=r;state.reviewPly=0;state.reviewFlip=false;state.reviewTrial=null;state.reviewLineMoves=[];state.reviewExplore=false;state.reviewSelect=null;state.scenarioMode=null;scenarioControls();
  $('review-explore').textContent='♟ جرب نقلة بنفسك';
  $('review').hidden=false;$('review-title').textContent=`${r.white} × ${r.black}`;
  drawReview();window.CoachAdvanced?.review(r);$('review').scrollIntoView({behavior:'smooth',block:'start'});
}catch(e){notify('تعذر فتح المباراة: '+e.message);}}
function goReview(ply){if(!state.review)return;state.scenarioMode=null;scenarioControls();state.reviewPly=Math.max(0,Math.min(state.review.total_plies,ply));state.reviewTrial=null;state.reviewLineMoves=[];state.reviewSelect=null;drawReview();}
function nextError(){const r=state.review;if(!r)return;const color=r.player_color,errors=r.plies.filter(p=>p.played_by===color&&p.lesson&&['هفوة كبيرة','خطأ','عدم دقة'].includes(p.quality)).map(p=>p.ply);if(!errors.length){notify('لا توجد أخطاء مصنفة في هذه المباراة');return;}goReview(errors.find(p=>p>state.reviewPly)||errors[0]);}
function reviewClick(sq){
 if(!state.reviewExplore||!state.review||state.busy)return;
 const entry=state.review.plies[state.reviewPly],legal=state.reviewTrial?.legal_moves||entry?.legal_moves||[];
 const fen=state.reviewTrial?.fen||entry.fen,piece=parseFen(fen)[sq];
 if(state.reviewSelect===sq){state.reviewSelect=null;drawReview();return;}
 if(state.reviewSelect){const moves=legal.filter(x=>x.startsWith(state.reviewSelect+sq));if(moves.length){chooseMove(moves,playReviewVariant);return;}}
 const turn=fen.split(' ')[1]==='w';
 if(piece&&(piece===piece.toUpperCase())===turn){state.reviewSelect=sq;drawReview();}
}
function reviewDrop(from,to){if(!state.reviewExplore||state.busy)return;
 const legal=state.reviewTrial?.legal_moves||state.review?.plies[state.reviewPly]?.legal_moves||[];
 const choices=legal.filter(x=>x.startsWith(from+to));chooseMove(choices,playReviewVariant);
}
async function playReviewVariant(uci){if(!state.review||state.busy)return;
 state.busy=true;state.reviewSelect=null;state.scenarioMode=null;scenarioControls();window.ChessBoardPro.optimistic($('review-board'),uci);
 try{
  const moves=[...state.reviewLineMoves,uci];
  const d=await api('/api/pro/v3/game/'+state.review.id+'/variation/'+state.reviewPly,{method:'POST',body:{moves}});
  state.reviewLineMoves=moves;state.reviewTrial=d;drawReview();
  notify('تمت النقلة '+d.san.at(-1)+' · تجربة من مباراة مكتملة');
 }catch(e){notify(e.message);}finally{state.busy=false;}
}
async function loadPuzzles(){try{const d=await api('/api/pro/puzzles?limit=150');state.puzzles=d.puzzles;if(state.puzzleIndex>=state.puzzles.length)state.puzzleIndex=0;drawPuzzle();}catch(e){notify(e.message);}}
function puzzleCurrent(){return state.puzzles[state.puzzleIndex]||null;}
function puzzleReset(){state.puzzleSelect=null;state.puzzleResult=null;state.puzzleReveal=false;state.puzzleHint=null;state.puzzleContinuation=null;drawPuzzle();}
function drawPuzzle(){
 const p=puzzleCurrent();
 if(!p){$('puzzle-board').replaceChildren();$('puzzle-label').textContent='لا توجد تمارين بعد';$('puzzle-description').textContent='بعد تحليل مبارياتك ستُنشأ تمارين من الأخطاء التي رصدها المحرك.';return;}
 const session=state.puzzleContinuation,result=state.puzzleResult;
 const latest=session?.history?.at(-1);
 const fen=session?.fen||result?.after_fen||p.fen;
 const legal=session?(session.ended?[]:session.turn===p.color?session.legal_moves:[]):result?[]:p.legal_moves;
 const selected=state.puzzleSelect,targets=selected?legal.filter(x=>x.startsWith(selected)).map(x=>x.slice(2,4)):[];
 const uci=latest?.uci||result?.played_uci||null;
 const grade=latest?.quality_code||(!session?result?.quality_code:null);
 $('puzzle-label').textContent=session?'تدريب من الموقف · ضد Stockfish':p.concept;
 $('puzzle-counter').textContent=`${state.puzzleIndex+1} / ${state.puzzles.length}`;
 $('puzzle-description').textContent=session?(session.ended?'انتهى هذا السيناريو. أعد المحاولة أو انتقل لتحدٍّ آخر.':'أكمل اللعب من نفس موقف التحدي ضد Stockfish. نقلة بنقلة.'):
   `أنت تلعب ${p.color==='white'?'بالأبيض':'بالأسود'} · ${p.quality}. اختر البديل الأفضل للنقلة ${p.move_number}.`;
 drawBoard($('puzzle-board'),fen,p.color,{selected,targets,legalMoves:legal,
  last:uci?[uci.slice(0,2),uci.slice(2,4)]:[],lastUci:uci,
  quality:grade?{code:grade,uci}:null,
  hintArrow:state.puzzleReveal&&!result&&!session?state.puzzleHint?.best_uci:null,
  onClick:puzzleClick,onMove:puzzleDrop});
 $('puzzle-hint-text').hidden=!(state.puzzleReveal&&state.puzzleHint);
 $('puzzle-hint-text').textContent=state.puzzleHint?`السهم الأخضر: ${state.puzzleHint.best_san}. ${state.puzzleHint.explanation_ar}`:'';
 $('puzzle-hint').disabled=!!session;
 $('puzzle-retry').hidden=!(result||session);
 $('puzzle-continue').hidden=!(result&&!session);
 $('puzzle-continue').disabled=state.busy;
 if(result){const correct=result.correct;
   const explanation=correct?result.success_explanation_ar:result.mistake_explanation_ar;
   const line=Array.isArray(result.best_line)&&result.best_line.length?`<p class="tiny scenario-line">خط المحرك الرئيسي: ${esc(result.best_line.slice(0,8).join(' ← '))}</p>`:'';
   const scenarios=Array.isArray(result.scenarios)?result.scenarios.slice(0,3).map((variant,i)=>
    `<div class="scenario-option"><strong>السيناريو ${i+1}: ${esc(variant.first||'—')}</strong><button class="btn btn-small btn-outline" type="button" data-puzzle-scenario="${i}">شاهد على الرقعة</button><p>${esc((variant.moves||[]).join(' ← '))}</p><small>سلسلة محتملة من المحرك عند هذا العمق؛ ليست نقلة إجبارية في كل موقف.</small></div>`).join(''):'';
   $('puzzle-result').innerHTML=`<div class="${correct?'correct':'incorrect'}"><strong>${correct?'✓ حل صحيح · ممتازة':'✧ فرصة للتعلم'}</strong><p>${esc(explanation|| (correct?'اختيار موفق.':'راجع النقلة الأفضل.'))}</p>${line}${scenarios?`<div class="scenario-options"><h3>قارن سيناريوهات المحرك</h3>${scenarios}</div>`:''}<small>${esc(result.quality_note||'درجة تعليمية للتحدي؛ ليست دقة Chess.com الرسمية.')}</small></div>`;
 }else $('puzzle-result').replaceChildren();
 $('puzzle-history').innerHTML=session?session.history.map((m,i)=>`<span class="move-tag">${esc(m.san)} ${window.MoveGrade.html(m.quality_code)}</span>`).join(''):'';
 if(session?.ended){$('puzzle-history').insertAdjacentHTML('beforeend',`<strong class="tiny"> · انتهت المتابعة: ${esc(session.result||'')}</strong>`);}
 $('puzzle-progress').textContent=`محاولات سابقة: ${p.attempts} · حلول صحيحة: ${p.solves} · سلسلة نجاح: ${p.streak}`;
}
function puzzleClick(square){
 const p=puzzleCurrent();if(!p||state.busy)return;
 const session=state.puzzleContinuation;
 if(state.puzzleResult&&!session)return;
 if(session?.ended)return;
 const fen=session?.fen||p.fen,legal=session?(session.turn===p.color?session.legal_moves:[]):p.legal_moves;
 if(state.puzzleSelect===square){state.puzzleSelect=null;drawPuzzle();return;}
 if(state.puzzleSelect){const choices=legal.filter(x=>x.startsWith(state.puzzleSelect+square));if(choices.length){chooseMove(choices,session?playPuzzleFollowup:attemptPuzzle);return;}}
 const piece=parseFen(fen)[square];if(piece&&(piece===piece.toUpperCase())===(p.color==='white')){state.puzzleSelect=square;drawPuzzle();}
}
function puzzleDrop(from,to){
 const p=puzzleCurrent();if(!p||state.busy)return;
 const session=state.puzzleContinuation;
 if(state.puzzleResult&&!session)return;
 const legal=session?(session.turn===p.color?session.legal_moves:[]):p.legal_moves;
 chooseMove(legal.filter(x=>x.startsWith(from+to)),session?playPuzzleFollowup:attemptPuzzle);
}
async function attemptPuzzle(uci){
 const p=puzzleCurrent();if(!p||state.busy)return;
 state.busy=true;state.puzzleSelect=null;window.ChessBoardPro.optimistic($('puzzle-board'),uci);
 try{const d=await api('/api/pro/puzzles/'+p.game_id+'/'+p.ply+'/attempt',{method:'POST',body:{uci}});
   state.puzzleResult=d;p.attempts++;if(d.correct){p.solves++;p.streak=d.streak;}else p.streak=0;
   notify(d.correct?'حل صحيح! يمكنك المتابعة أو إعادة المحاولة.':'جرّب البديل الأقوى أو تابع من نقلك.');
 }catch(e){notify(e.message);}finally{state.busy=false;drawPuzzle();}
}
async function revealPuzzleHint(){
 const p=puzzleCurrent();if(!p||state.puzzleContinuation)return;
 if(state.puzzleReveal){state.puzzleReveal=false;drawPuzzle();return;}
 try{const result=await api('/api/pro/puzzles/'+p.game_id+'/'+p.ply+'/hint');
   state.puzzleHint=result;state.puzzleReveal=true;drawPuzzle();
 }catch(e){notify(e.message);}
}
async function continuePuzzle(){
 const p=puzzleCurrent(),r=state.puzzleResult;if(!p||!r||state.busy)return;
 state.busy=true;
 try{state.puzzleContinuation=await api('/api/pro/puzzles/'+p.game_id+'/'+p.ply+'/continue',{method:'POST',body:{uci:r.played_uci}});
   state.puzzleSelect=null;notify('بدأ اللعب من موقف التحدي ضد المحرك.');
 }catch(e){notify(e.message);}finally{state.busy=false;drawPuzzle();}
}
async function playPuzzleFollowup(uci){
 const session=state.puzzleContinuation;if(!session||state.busy)return;
 state.busy=true;state.puzzleSelect=null;window.ChessBoardPro.optimistic($('puzzle-board'),uci);
 try{state.puzzleContinuation=await api('/api/pro/training/'+session.session_id+'/move',{method:'POST',body:{uci}});
  if(state.puzzleContinuation.ended)notify('انتهى هذا السيناريو.');
 }catch(e){notify(e.message);}finally{state.busy=false;drawPuzzle();}
}
function nextPuzzle(){if(!state.puzzles.length)return;state.puzzleIndex=(state.puzzleIndex+1)%state.puzzles.length;puzzleReset();}
function drawTraining(){const s=state.session;const fen=s?.fen||'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
  const color=s?(state.trainFlip?(s.color==='white'?'black':'white'):s.color):'white';
  const targets=state.trainSelect&&s?s.legal_moves.filter(x=>x.startsWith(state.trainSelect)).map(x=>x.slice(2,4)):[];
  const last=s?.history?.at(-1)?.uci;
  const lastGrade=s?.history?.at(-1)?.quality_code;
  drawBoard($('training-board'),fen,color,{selected:state.trainSelect,targets,
   last:last?[last.slice(0,2),last.slice(2,4)]:[],lastUci:last,
   quality:lastGrade?{code:lastGrade,uci:last}:null,hintArrow:state.trainHint?.best_uci,
   onClick:trainingClick,legalMoves:s&&!s.ended&&!state.busy&&((s.fen.split(' ')[1]==='w')===(s.color==='white'))?s.legal_moves:[],onMove:trainingDrop});
  $('training-hint').disabled=!s||s.ended;
  $('training-status').textContent=!s?'لم تبدأ مباراة':s.ended?'انتهت: '+s.result:'أنت تلعب '+(s.color==='white'?'بالأبيض':'بالأسود');
  $('training-moves').innerHTML=s?s.history.map((m,i)=>`<span class="move-tag">${Math.floor(i/2)+1}${m.color==='white'?'.':'...'} ${esc(m.san)} ${window.MoveGrade.html(m.quality_code)}</span>`).join(''):'';
}
function trainingClick(sq){const s=state.session;if(!s||s.ended||state.busy)return;
  const turn=s.fen.split(' ')[1]==='w'?'white':'black';if(turn!==s.color)return;
  const piece=parseFen(s.fen)[sq];if(state.trainSelect===sq){state.trainSelect=null;drawTraining();return;}
  if(state.trainSelect){const possible=s.legal_moves.filter(x=>x.startsWith(state.trainSelect+sq));if(possible.length){chooseMove(possible,playTraining);return;}}
  if(piece&&(piece===piece.toUpperCase())===(s.color==='white')){state.trainSelect=sq;drawTraining();}
}
function trainingDrop(from,to){const s=state.session;if(!s||s.ended||state.busy)return;
 chooseMove(s.legal_moves.filter(x=>x.startsWith(from+to)),playTraining);
}
async function startTraining(){const btn=$('training-start');busy(btn,true,'بدء المباراة...');try{state.session=await api('/api/pro/training',{method:'POST',body:{color:$('training-color').value,strength:Number($('training-strength').value)}});state.trainSelect=null;state.trainFlip=false;state.trainHint=null;
  $('training-feedback').textContent='اختر قطعة ومربع الوصول. زر التلميح يعطي أفضل نقلة في تدريبك المستقل.';drawTraining();notify('بدأت المباراة التدريبية');}catch(e){notify(e.message);}finally{busy(btn,false);}}
async function playTraining(uci){state.busy=true;state.trainSelect=null;state.trainHint=null;window.ChessBoardPro.optimistic($('training-board'),uci);$('training-status').textContent='محرك Stockfish يفكر...';try{const result=await api('/api/pro/training/'+state.session.session_id+'/move',{method:'POST',body:{uci}});state.session=result;
  const f=result.feedback;$('training-feedback').innerHTML=`<strong>${esc(f.label)} · ${esc(result.your_move_san)}</strong><p>${esc(f.message)}</p>${f.best_san?`<div class="best-move"><span>اقتراح المحرك</span><strong>${esc(f.best_san)}</strong></div>`:''}<small>رد Stockfish: ${esc(result.engine_move_san||'انتهت المباراة')}</small>`;
  drawTraining();if(result.ended)notify('انتهت المباراة التدريبية: '+result.result);
}catch(e){notify(e.message);}finally{state.busy=false;}}
async function hintTraining(){const s=state.session;if(!s)return;const btn=$('training-hint');busy(btn,true,'تحليل...');try{const d=await api('/api/pro/training/'+s.session_id+'/hint');state.trainHint=d;drawTraining();$('training-feedback').innerHTML=`<strong>✧ تلميح: ${esc(d.concept)}</strong><div class="best-move"><span>أفضل نقلة</span><strong>${esc(d.best_san)}</strong></div><p>${esc(d.explanation_ar)}</p><p class="tiny muted">الخط المقترح: ${esc(d.line.join('، '))}</p>`;notify('ظهر التلميح');}catch(e){notify(e.message);}finally{busy(btn,false);}}
function bar(label,n,max){return `<div class="bar-row"><span>${esc(label)}</span><progress class="progress" max="${max||1}" value="${n}"></progress><strong>${esc(n)}</strong></div>`;}
async function loadInsights(){try{const d=state.dashboard||await api('/api/pro/dashboard');$('insights-content').innerHTML=`<div class="stats-grid">${stat('♕',d.wins,'فوز')}${stat('♟',d.losses,'خسارة')}${stat('♧',d.draws,'تعادل')}${stat('◎',d.total_reviewed_moves,'نقلة تم تقييمها')}</div><div class="two-cols"><section class="panel"><h2>الأخطاء بحسب مرحلة اللعب</h2><div class="insight-chart">${d.weak_phases.length?d.weak_phases.map(x=>bar(x.phase,x.errors,Math.max(...d.weak_phases.map(y=>y.errors)))).join(''):'<p class="muted">لا توجد بيانات كافية.</p>'}</div><div class="notice" class="spaced">${esc(d.weak_phases[0]?.tip||'الاستمرار في التدريب يساعد على تطوير مستواك.')}</div></section><section class="panel"><h2>تصنيف الأخطاء</h2><div class="insight-chart">${Object.entries(d.mistake_categories).length?Object.entries(d.mistake_categories).map(([k,v])=>bar(k,v,Math.max(...Object.values(d.mistake_categories)))).join(''):'<p class="muted">لا أخطاء مصنفة حالياً.</p>'}</div></section></div><section class="panel" class="spaced"><h2>الافتتاحات المتكررة</h2>${d.openings.length?d.openings.map(o=>`<div class="opening-row"><div><strong>${esc(o.name)}</strong><br/><small>فوز ${o.wins} · خسارة ${o.losses} · تعادل ${o.draws}</small></div><span class="pill">${o.games} مباراة</span></div>`).join(''):'<p class="muted">لا توجد افتتاحات مسجلة.</p>'}<p class="tiny muted" class="spaced">${esc(d.notice)}</p></section>`;}catch(e){notify(e.message);}}
async function loadPlan(){try{const p=await api('/api/pro/plan');$('plan-content').innerHTML=`<div class="focus-block"><div class="focus-emoji">✦</div><div><strong>التركيز الحالي: ${esc(p.focus)}</strong><small>بناءً على ${p.based_on} مباراة</small></div></div><div class="plan-grid">${p.days.map((d,i)=>`<article class="plan-day"><span class="day-name">اليوم ${i+1} · ${esc(d.day)} · ${d.minutes} دقيقة</span><h3>${esc(d.title)}</h3><p>${esc(d.action)}</p></article>`).join('')}</div><p class="tiny muted" class="spaced">${esc(p.note)}</p>`;}catch(e){notify(e.message);}}
async function syncGames(){const btn=$('sync-button');busy(btn,true,'مزامنة...');try{const result=await api('/api/sync',{method:'POST'});notify(result.error?'المزامنة فشلت: '+result.error:'المزامنة اكتملت · جديد: '+result.new_games_analyzed,6000);await loadDashboard();if(state.view==='games')await loadGames(true);}catch(e){notify(e.message);}finally{busy(btn,false);}}
// Archived-game scenario explorer: verified on the server before every step.
function scenarioControls(){
 const el=$('scenario-controls');if(!el)return;
 const mode=state.scenarioMode;el.hidden=!mode;
 if(mode){$('scenario-title').textContent=`السيناريو ${mode.index+1} · ${mode.cursor} / ${mode.moves.length} نصف نقلة · ${mode.label}`;
  $('scenario-explanation').textContent=mode.summary||'تسلسل محتمل وفق عمق المحرك؛ ليس إجبارياً بكل رد.';
  $('scenario-next').disabled=state.busy||mode.cursor>=mode.moves.length;
  $('scenario-back').disabled=state.busy||mode.cursor===0;
 }
}
async function openScenario(index){
 const review=state.review,entry=review?.plies[state.reviewPly],scenarios=entry?.lesson?.scenarios||[];
 const line=scenarios[index];if(!line?.pv_uci?.length){notify('أعد تحليل المباراة للحصول على خط قابل للعرض.');return;}
 const anchor=Math.max(0,state.reviewPly-1);
 goReview(anchor);
 state.reviewExplore=true;state.reviewTrial=null;state.reviewLineMoves=[];
 state.scenarioMode={index,label:line.first||'',summary:line.summary||'',moves:line.pv_uci,cursor:0,anchor,token:Date.now()};
 $('review-explore').textContent='إيقاف تجربة النقلات';scenarioControls();drawReview();
 $('review-board').scrollIntoView({behavior:'smooth',block:'center'});notify('ابدأ تشغيل السيناريو بالنقر على «النقلة التالية» أو «تشغيل الخط».');
}
async function scenarioStep(delta){
 const mode=state.scenarioMode;if(!mode||state.busy)return false;
 const next=Math.max(0,Math.min(mode.moves.length,mode.cursor+delta));if(next===mode.cursor)return false;
 const codes=mode.moves.slice(0,next),uci=delta>0?mode.moves[mode.cursor]:null;
 state.busy=true;
 if(uci)window.ChessBoardPro.optimistic($('review-board'),uci);
 try{
  const d=await api('/api/pro/v3/game/'+state.review.id+'/variation/'+mode.anchor,{method:'POST',body:{moves:codes}});
  if(state.scenarioMode!==mode)return false;
  mode.cursor=next;state.reviewTrial=d;state.reviewLineMoves=codes;drawReview();scenarioControls();return true;
 }catch(e){notify('تعذر تطبيق السيناريو: '+e.message);drawReview();return false;}
 finally{state.busy=false;scenarioControls();}
}
async function scenarioAutoplay(){
 const mode=state.scenarioMode;if(!mode)return;
 $('scenario-autoplay').disabled=true;
 try{while(state.scenarioMode===mode&&mode.cursor<mode.moves.length){
  const ok=await scenarioStep(1);if(!ok)break;
  await new Promise(r=>setTimeout(r,400));
 }}finally{$('scenario-autoplay').disabled=false;}
}
function scenarioContinue(){
 if(!state.scenarioMode)return;
 state.scenarioMode=null;scenarioControls();state.reviewExplore=true;
 drawReview();notify('يمكنك الآن تحريك أي نقلة قانونية من الوضع الحالي مباشرة على الرقعة.');
}
window.CoachScenario={open:openScenario};
async function refreshDeepStatus(){
 const target=$('deep-status');if(!target||!state.key)return;
 try{
  const d=await api('/api/pro/v5/deep/status');
  if(!d.worker_ready){target.textContent=d.notice;return;}
  const states=d.states||{},first=d.current?.find(x=>x.status==='running');
  target.innerHTML=`<div class="deep-stats"><strong>${d.completed} تحليل مكتمل</strong><span>${d.waiting} بانتظار التحليل</span><span>${states.error||0} بحاجة للمراجعة</span><span>${esc(d.archive?.archive_last_month||'استيراد الأرشيف جارٍ')}</span></div>${first?`<div class="deep-progress">${esc(first.white)} × ${esc(first.black)} · ${first.positions_done}/${first.positions_total} وضعية · ${first.percent}%<progress max="100" value="${first.percent}"></progress></div>`:'<p>لا توجد مباراة قيد التحليل الآن. العامل يفحص الأرشيف بصورة دورية على السيرفر.</p>'}<p class="tiny muted">حتى 120 ثانية للوضعية حسب إعدادات العامل. إغلاق المتصفح لا يوقفه.</p>`;
 }catch(e){target.textContent='تعذر قراءة حالة العامل: '+e.message;}
}
// Event wiring
$('connect-form').addEventListener('submit',async event=>{event.preventDefault();const candidate=$('api-key').value.trim();$('connect-error').textContent='';state.key=candidate;const btn=$('connect-button');busy(btn,true,'جارٍ التحقق...');try{const status=await api('/api/status');$('username').textContent=status.username;$('api-key').value='';$('connection').hidden=true;$('app-content').hidden=false;$('sync-button').disabled=false;
  notify('اتصال ناجح · أهلاً بك');setView(VIEW_TITLES[location.hash.slice(1)]?location.hash.slice(1):'dashboard');
}catch(e){state.key='';$('connect-error').textContent=e.message;}finally{busy(btn,false);}});
document.addEventListener('click',e=>{const el=e.target.closest('[data-view],[data-go],[data-game],[data-ply]');if(!el)return;if(el.dataset.view)setView(el.dataset.view);if(el.dataset.go)setView(el.dataset.go);if(el.dataset.game){setView('games');openGame(el.dataset.game);}if(el.dataset.ply)goReview(Number(el.dataset.ply));});
$('menu-button').addEventListener('click',()=>document.querySelector('.sidebar').classList.toggle('open'));
$('sync-button').addEventListener('click',syncGames);
$('load-more-games').addEventListener('click',()=>{state.gamePage++;loadGames(false);});
$('close-review').addEventListener('click',()=>{$('review').hidden=true;state.review=null;});
$('review-start').addEventListener('click',()=>goReview(0));$('review-prev').addEventListener('click',()=>goReview(state.reviewPly-1));
$('review-next').addEventListener('click',()=>goReview(state.reviewPly+1));$('review-end').addEventListener('click',()=>goReview(state.review?.total_plies||0));
$('review-range').addEventListener('input',e=>goReview(Number(e.target.value)));$('review-flip').addEventListener('click',()=>{state.reviewFlip=!state.reviewFlip;drawReview();});
$('review-next-error').addEventListener('click',nextError);
$('scenario-next').addEventListener('click',()=>scenarioStep(1));
$('scenario-back').addEventListener('click',()=>scenarioStep(-1));
$('scenario-autoplay').addEventListener('click',scenarioAutoplay);
$('scenario-continue').addEventListener('click',scenarioContinue);
$('scenario-exit').addEventListener('click',()=>{state.scenarioMode=null;scenarioControls();goReview(state.reviewPly);});
$('deep-refresh').addEventListener('click',refreshDeepStatus);
$('review-explore').addEventListener('click',()=>{state.reviewExplore=!state.reviewExplore;
  state.reviewTrial=null;state.reviewLineMoves=[];state.reviewSelect=null;
  $('review-explore').textContent=state.reviewExplore?'إيقاف تجربة النقلات':'♟ جرب نقلة بنفسك';drawReview();});
$('review-reset-variation').addEventListener('click',()=>{state.reviewTrial=null;state.reviewLineMoves=[];state.reviewSelect=null;drawReview();});
$('review-reanalyze').addEventListener('click',async()=>{if(!state.review)return;const btn=$('review-reanalyze');busy(btn,true,'جارٍ تحليل المباراة...');const gid=state.review.id,ply=state.reviewPly;try{await api('/api/pro/v5/deep/requeue/'+gid,{method:'POST'});notify('أُضيفت المباراة لقائمة التحليل العميق في الخلفية. يمكن إغلاق المتصفح.');refreshDeepStatus();}catch(e){notify(e.message);}finally{busy(btn,false);}});
$('puzzle-result').addEventListener('click',async e=>{
 const btn=e.target.closest('[data-puzzle-scenario]');if(!btn)return;
 const p=puzzleCurrent();if(!p)return;
 setView('games');await openGame(p.game_id);goReview(p.ply);await openScenario(Number(btn.dataset.puzzleScenario));
});
$('puzzle-skip').addEventListener('click',nextPuzzle);$('puzzle-hint').addEventListener('click',revealPuzzleHint);$('puzzle-retry').addEventListener('click',puzzleReset);$('puzzle-continue').addEventListener('click',continuePuzzle);
$('training-strength').addEventListener('input',e=>$('strength-label').textContent=e.target.value+' / 20');
$('training-start').addEventListener('click',startTraining);$('training-hint').addEventListener('click',hintTraining);$('training-flip').addEventListener('click',()=>{state.trainFlip=!state.trainFlip;drawTraining();});
drawTraining();

setInterval(()=>{if(state.key&&state.view==='dashboard'&&!document.hidden)refreshDeepStatus();},30000);
