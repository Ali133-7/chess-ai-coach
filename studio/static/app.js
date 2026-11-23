'use strict';
const $=id=>document.getElementById(id);
const S={me:null,csrf:'',view:'home',dashboard:null,games:[],filter:'all',scope:'mine',page:1,review:null,ply:0,flip:false,
 scenario:null,scenarioStep:0,practicing:false,practiceTrail:[],selected:null,lesson:null,lessonSelect:null,lessonHintArrow:null,lessonSide:'any',lessonPlan:null,lessonResult:null,lessonReveal:false,lessonMode:'original',lessonScenarioIndex:-1,lessonStep:0,lessonPracticeTrail:[],lessonPracticeFen:null,lessonPracticeLegal:[],lessonSequence:0,busy:false};
const LABELS={book:'من الكتاب',brilliant:'مدهشة',excellent:'ممتازة',good:'جيدة',weak:'ضعيفة',missed:'ضياع فرصة',mistake:'خطأ',blunder:'خطأ فادح',unrated:'غير مُقيّمة'};
const SYMBOLS={book:'▣',brilliant:'!!',excellent:'!',good:'✓',weak:'?!',missed:'○',mistake:'?',blunder:'??',unrated:'–'};
const titles={billing:'الخطط والاشتراك',learning:'مساري التعليمي',knowledge:'مركز المعرفة والتحليل',play:'العب وتعلّم',home:'الرئيسية',games:'المباريات والتحليل',grades:'تقييمات النقلات',course:'مسار التطوير',settings:'إعداداتي',admin:'إدارة المنصة'};
const ESC={'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'};
const esc=text=>String(text??'').replace(/[&<>"']/g,x=>ESC[x]);
const fmtDate=x=>new Date(x*1000).toLocaleDateString(window.I18n?.locale||'ar-IQ',{year:'numeric',month:'short',day:'numeric'});
const badge=g=>`<span class="grade-tag grade-${esc(g||'unrated')}">${esc(SYMBOLS[g]||'–')}</span>`;
const toast=text=>{const n=$('toast');n.textContent=text;n.classList.add('show');setTimeout(()=>n.classList.remove('show'),3800);};
async function request(path,{method='GET',body,signal}={}){
 if(method==='GET'&&!signal&&window.StudioRequests)return window.StudioRequests.get((S.me?.id||'anonymous')+':'+(window.I18n?.lang||'ar'),path,()=>rawRequest(path,{method,body}));
 if(method!=='GET')window.StudioRequests?.invalidate();
 return rawRequest(path,{method,body,signal});
}
async function rawRequest(path,{method='GET',body,signal}={}){
 const requestSession=S.csrf;
 const opt={method,signal,credentials:'same-origin',cache:'no-store',headers:{'Accept':'application/json','Accept-Language':window.I18n?.lang||'ar'}};
 if(method!=='GET')opt.headers['X-CSRF-Token']=S.csrf;
 if(body!==undefined){opt.headers['Content-Type']='application/json';opt.body=JSON.stringify(body);}
 let response;
 try{response=await fetch('/api'+path,opt);}catch(e){if(e.name==='AbortError')throw e;throw new Error('تعذر الاتصال بالخادم');}
 const data=await response.json().catch(()=>({}));
 if(requestSession!==S.csrf&&!path.startsWith('/auth/'))throw new DOMException('Session changed','AbortError');
 if(!response.ok){if(response.status===401&&S.me&&requestSession===S.csrf){S.me=null;showAuth();}throw new Error(typeof data.detail==='string'?data.detail:(data.detail?.message||(Array.isArray(data.detail)?data.detail.map(x=>x.msg).join(' · '):('خطأ '+response.status))));}
 return data;
}
async function boot(){try{S.me=await request('/me');S.csrf=S.me.csrf;showApp();}catch{showAuth();}}
function showAuth(){S.csrf='';S.review=null;S.lesson=null;S.dashboard=null;S.games=[];window.StudioRequests?.invalidate();document.dispatchEvent(new CustomEvent('studio:session',{detail:{id:null}}));$('auth-screen').hidden=false;$('workspace').hidden=true;}
function showApp(){document.dispatchEvent(new CustomEvent('studio:session',{detail:{id:S.me.id}}));$('auth-screen').hidden=true;$('workspace').hidden=false;$('admin-nav').hidden=S.me.role!=='admin';
 $('current-player').textContent=S.me.chess_username||'اربط حساب Chess.com';setTheme(S.me.theme);document.body.dataset.board=S.me.board_theme||'classic';
 switchView(!S.me.chess_username?'settings':'home');}
function setTheme(theme){const value=theme==='system'?(matchMedia('(prefers-color-scheme: light)').matches?'light':'dark'):theme;
 document.body.dataset.theme=value;$('theme-toggle').textContent=value==='light'?'☾':'☀';}
let registerMode=false;
$('tab-login').addEventListener('click',()=>{registerMode=false;$('tab-login').classList.add('active');$('tab-register').classList.remove('active');$('auth-submit').textContent='دخول';});
$('tab-register').addEventListener('click',()=>{registerMode=true;$('tab-register').classList.add('active');$('tab-login').classList.remove('active');$('auth-submit').textContent='إنشاء حساب';});
$('auth-form').addEventListener('submit',async e=>{e.preventDefault();$('auth-error').textContent='';const btn=$('auth-submit');btn.disabled=true;
 try{const d=await request('/auth/'+(registerMode?'register':'login'),{method:'POST',body:{email:$('auth-email').value,password:$('auth-pass').value}});
  S.csrf=d.csrf;S.me=await request('/me');$('auth-pass').value='';showApp();
 }catch(error){$('auth-error').textContent=error.message;}finally{btn.disabled=false;}});
$('logout').addEventListener('click',async()=>{try{await request('/auth/logout',{method:'POST'});S.me=null;S.csrf='';showAuth();location.reload();}catch(e){toast(e.message);}});
$('menu').addEventListener('click',()=>document.querySelector('.sidebar').classList.toggle('open'));
$('theme-toggle').addEventListener('click',async()=>{const theme=document.body.dataset.theme==='light'?'dark':'light';setTheme(theme);if(S.me){$('theme').value=theme;await saveSettings(true);}});
function switchView(view){if(!(view in titles)||view==='admin'&&S.me?.role!=='admin')return;S.view=view;
 for(const node of document.querySelectorAll('.view'))node.hidden=node.id!=='view-'+view;
 for(const b of document.querySelectorAll('#nav button'))b.classList.toggle('active',b.dataset.view===view);
 $('page-title').textContent=titles[view];document.querySelector('.sidebar').classList.remove('open');
 if(view==='billing')window.loadBilling?.();
 if(view==='settings')window.loadBillingSummary?.();
 if(view==='learning')window.loadLearningPath?.();
 if(view==='knowledge')window.loadKnowledge?.();
 if(view==='play')window.loadGroqPlay?.();
 if(view==='home')loadHome();if(view==='games')loadGames();if(view==='grades')loadGrades();
 if(view==='course')loadCourse();if(view==='settings')showSettings();if(view==='admin')loadAdmin();document.dispatchEvent(new CustomEvent('studio:view',{detail:{view}}));}
document.addEventListener('click',e=>{const b=e.target.closest('button[data-view]');if(b)switchView(b.dataset.view);});
function stat(v,label){return `<div class="stat"><strong>${esc(v)}</strong><span>${esc(label)}</span></div>`;}
async function loadRatingTrend(){
 try{
  const fmt=S.me?.rating_format||'rapid';const d=await request('/ratings/history?format='+encodeURIComponent(fmt));
  const values=d.items||[];if(values.length<2){$('rating-trend').innerHTML='<p class="tiny muted">منحنى التصنيف يظهر بعد استيراد مباريات مصنفة كافية.</p>';return;}
  const min=Math.min(...values.map(x=>x.rating))-20,max=Math.max(...values.map(x=>x.rating))+20;
  const pts=values.map((v,i)=>`${(i/(values.length-1)*100).toFixed(2)},${(100-(v.rating-min)/(max-min)*100).toFixed(2)}`).join(' ');
  $('rating-trend').innerHTML='<h3 class="subheading">تاريخ تصنيف '+esc(fmt.toUpperCase())+' من PGN الرسمي</h3>'+
   '<svg viewBox="0 0 100 100" role="img" aria-label="تطور التصنيف خلال المباريات السابقة" preserveAspectRatio="none"><polyline fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" points="'+pts+'" /></svg>'+
   '<p class="tiny muted">من '+values[0].rating+' إلى '+values.at(-1).rating+' · آخر '+values.length+' مباراة مصنفة متاحة</p>';
 }catch(e){$('rating-trend').innerHTML='';}
}
function showRatings(items){const r=items||[];
 $('ratings').innerHTML=r.length?r.map(x=>`<div class="rating-card"><small>${esc(x.format.toUpperCase())} · Chess.com</small><strong>${esc(x.rating??'—')}</strong><small>الأعلى ${esc(x.best??'—')} · ${esc(x.wins||0)} فوز</small></div>`).join(''):
 '<p class="muted">بانتظار استيراد التصنيفات المنشورة من Chess.com.</p>';}
function gameEntry(x){return `<div class="game-card" data-open-game="${Number(x.id)}"><div><strong>${esc(x.white)} × ${esc(x.black)}</strong><small>${fmtDate(x.finished_at)} · ${esc(x.stage==='done'?'تحليل عميق جاهز':x.stage==='running'?'جارٍ التحليل':x.stage==='error'?'خطأ في التحليل':x.stage==='cancelled'?'أُلغي التحليل — يمكن استئنافه':'قيد الانتظار')}</small></div><div>${esc(x.grade_count??'')}<small>${esc(x.result)}</small></div></div>`;}
async function loadHome(){try{const d=await request('/dashboard?summary_only=true');S.dashboard=d;
 const g=d.games;$('summary').innerHTML=stat(g.total||0,'مباراة مستوردة')+stat(g.done||0,'مباراة محللة')+stat(g.pending||0,'بانتظار التحليل')+stat(d.lessons_passed+' / '+d.lessons_total,'دروس مجتازة');
 showRatings(d.ratings);loadRatingTrend();const done=Number(g.done||0),total=Number(g.total||0);const pct=total?100*done/total:0;
 $('queue').innerHTML=`<div class="between"><strong>${done} / ${total} مباراة</strong><small>${pct.toFixed(1)}%</small></div><progress class="progress" max="100" value="${pct}"></progress><p class="tiny muted">التحليل في السيرفر يستمر حتى بعد إغلاق المتصفح. قد يستغرق وقتاً طويلاً مع 120 ثانية لكل وضعية.</p>`;
 $('course-short').innerHTML=`<p>اجتزت ${d.lessons_passed} من أصل ${d.lessons_total} دروس.</p><button data-view="course">ابدأ المسار الدراسي</button>`;
 $('recent-games').innerHTML=d.recent.length?d.recent.slice(0,3).map(gameEntry).join(''):'<p class="muted">اربط حساب Chess.com لبدء الاستيراد التلقائي.</p>';
 }catch(e){if(e.name!=='AbortError')toast(e.message);}}
$('refresh').addEventListener('click',loadHome);
function filterButton(g){return `<button class="${S.filter===g?'active':''}" data-grade-filter="${g}">${g==='all'?'جميع النقلات':LABELS[g]}</button>`;}
let gamesReadSequence=0;
async function loadGames(){const seq=++gamesReadSequence;try{const path='/games?limit=20&page='+S.page+'&grade='+S.filter+'&scope='+S.scope;const d=await (window.StudioRequests?window.StudioRequests.latest('games',path):request(path));if(seq!==gamesReadSequence||S.view!=='games')return;S.games=d.games;
 $('game-filters').innerHTML=['all',...Object.keys(LABELS)].map(filterButton).join('');
 $('game-list').innerHTML=d.games.length?d.games.map(gameEntry).join(''):'<p class="muted">لا توجد مباريات محللة في هذا التصنيف بعد.</p>';
 $('game-pagination').innerHTML=`<button id="page-prev" ${S.page===1?'disabled':''}>السابق</button><span>${S.page} / ${Math.max(1,Math.ceil(d.total/20))}</span><button id="page-next" ${S.page*20>=d.total?'disabled':''}>التالي</button>`;
 $('page-prev').onclick=()=>{S.page--;loadGames()};$('page-next').onclick=()=>{S.page++;loadGames()};
 }catch(e){if(e.name!=='AbortError')toast(e.message);}}
document.addEventListener('click',e=>{const g=e.target.closest('[data-grade-filter]');if(g){S.filter=g.dataset.gradeFilter;S.page=1;switchView('games');}
 const x=e.target.closest('[data-open-game]');if(x){switchView('games');openGame(Number(x.dataset.openGame));}});
$('scope').addEventListener('change',e=>{S.scope=e.target.value;$('grade-scope').value=S.scope;S.page=1;loadGames();});
$('grade-scope').addEventListener('change',e=>{S.scope=e.target.value;$('scope').value=S.scope;S.page=1;loadGrades();});
async function loadGrades(){try{const d=await request('/grades?scope='+S.scope);$('grade-cards').innerHTML=Object.keys(LABELS).map(k=>`<button class="grade-card" data-grade-filter="${k}">${badge(k)} <strong>${Number(d.counts[k]||0)}</strong><small>${esc(LABELS[k])} · عرض المباريات</small></button>`).join('');}catch(e){if(e.name!=='AbortError')toast(e.message);}}
let reviewReadSequence=0;
async function openGame(id){const seq=++reviewReadSequence,owner=S.me?.id;try{S.teacherArrow=null;S.reviewTeacherToken=(S.reviewTeacherToken||0)+1;S.reviewTeacherPlan=null;$('review-teacher').hidden=true;const nextReview=await (window.StudioRequests?window.StudioRequests.latest('review','/games/'+id):request('/games/'+id));if(seq!==reviewReadSequence||S.me?.id!==owner)return;S.review=nextReview;if(['pending','running'].includes(nextReview.stage))request('/analysis/jobs/'+id+'/action',{method:'POST',body:{action:'prioritize'}}).catch(()=>{});S.ply=0;S.flip=false;S.scenario=null;S.practicing=false;S.practiceTrail=[];S.selected=null;
 $('review').hidden=false;$('review-title').textContent=S.review.white+' × '+S.review.black;renderPerGameStats();
 window.openReviewModal();drawReview();
 }catch(e){if(e.name!=='AbortError')toast(e.message);}}
function renderPerGameStats(){
 const r=S.review;if(!r)return;
 const ownWhite=(r.white||'').toLowerCase()===(S.me.chess_username||'').toLowerCase();
 const mine=r.moves.filter(m=>(m.ply%2===1)===ownWhite&&m.loss_cp!==undefined&&m.loss_cp!==null);
 const acpl=mine.length?mine.reduce((sum,m)=>sum+Number(m.loss_cp),0)/mine.length:null;
 const accuracy=mine.length?mine.reduce((sum,m)=>sum+Math.exp(-Number(m.loss_cp)/250)*100,0)/mine.length:null;
 const counts={};for(const m of r.moves)counts[m.grade||'unrated']=(counts[m.grade||'unrated']||0)+1;
 $('review-metrics').innerHTML=stat(accuracy===null?'—':accuracy.toFixed(1)+'%','دقة تقديرية')+
  stat(acpl===null?'—':(acpl/100).toFixed(2),'متوسط تراجع الأفضلية (من قيمة البيدق)')+
  stat(r.moves.length,'عدد أنصاف النقلات')+
  stat(r.stage==='done'?'مكتمل':r.completed_positions+' / '+r.total_positions,'التحليل العميق');
 $('review-grade-summary').innerHTML=Object.keys(LABELS).filter(k=>counts[k]).map(k=>`<button data-review-grade="${k}" class="review-grade-button">${badge(k)} ${esc(LABELS[k])} <strong>${counts[k]}</strong></button>`).join('');
 const series=r.moves.filter(m=>m.eval_cp_white!==undefined&&m.eval_cp_white!==null).map(m=>m.eval_cp_white);
 if(series.length>1){
  const cap=v=>Math.max(-1200,Math.min(1200,v));
  const points=series.map((v,i)=>`${(i/(series.length-1)*100).toFixed(2)},${(50-cap(Number(v))/24).toFixed(2)}`).join(' ');
  $('review-eval-chart').innerHTML='<p class="tiny muted">تطور أفضلية الأبيض (تقدير Stockfish)</p><svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-label="تطور التقييم" role="img"><polyline fill="none" stroke="currentColor" stroke-width="1.8" points="'+points+'" /></svg>';
 }else $('review-eval-chart').innerHTML='<p class="tiny muted">رسم الأفضلية يتوفر بعد التحليل العميق.</p>';
}
$('review-grade-summary').addEventListener('click',e=>{
 const target=e.target.closest('[data-review-grade]');if(!target||!S.review)return;
 const relevant=S.review.moves.filter(m=>m.grade===target.dataset.reviewGrade);
 if(!relevant.length)return;
 const next=relevant.find(m=>m.ply>S.ply)||relevant[0];goPly(next.ply);
});
function findMove(){return S.review?.moves[S.ply-1]||null;}
function drawReview(){const r=S.review;if(!r)return;const entry=findMove();
 const position=S.practicing?(S.scenario?.practiceFen||entry?.fen_before):S.scenario?.fens?.[S.scenarioStep]||entry?.fen_after||r.moves[0]?.fen_before||'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
 const mainLast=S.scenario&&!S.practicing?S.scenario.moves[S.scenarioStep-1]:entry?.uci;
 const orientation=S.flip?(r.white.toLowerCase()===(S.me?.chess_username||'')?'black':'white'):(r.white.toLowerCase()===(S.me?.chess_username||'')?'white':'black');
 const allowed=S.practicing?(S.scenario?.legalMoves||[]):[];
 const targets=S.selected?allowed.filter(m=>m.startsWith(S.selected)).map(m=>m.slice(2,4)):[];
 window.ChessBoardPro.render($('board'),position,orientation,{last:mainLast?[mainLast.slice(0,2),mainLast.slice(2,4)]:[],lastUci:mainLast,
    quality:entry&&(!S.scenario)?{code:entry.grade,uci:entry.uci}:null,hintArrow:(S.scenario&&!S.practicing?S.scenario.moves[S.scenarioStep]||null:S.teacherArrow||null),selected:S.selected,targets,legalMoves:allowed,
    onMove:reviewDrop,onClick:reviewClick});
 $('move-indicator').textContent=entry?`${Math.floor((S.ply+1)/2)}${S.ply%2?'.':'...'} ${entry.san}`:'بداية المباراة';
 $('moves').innerHTML=r.moves.map(m=>`<button class="move-pill ${m.ply===S.ply?'active':''}" data-ply="${m.ply}">${Math.ceil(m.ply/2)}${m.ply%2?'.':'...'} ${esc(m.san)} ${badge(m.grade)}</button>`).join('');
 $('scenario-controls').hidden=!S.scenario;
 $('exit-scenario').hidden=!S.scenario;
 if(!entry){$('move-detail').innerHTML='<p class="muted">اختر نقلة لرؤية حكم Stockfish وأفضل بدائلها.</p>';$('scenarios').innerHTML='';return;}
 const ev=entry.eval_cp_white!=null?(entry.eval_cp_white/100).toFixed(2):'—';
 $('move-detail').innerHTML=`<div class="notice"><strong>${badge(entry.grade)} ${esc(LABELS[entry.grade]||'غير مُقيّمة')}</strong>
   <p>النقلة: <b>${esc(entry.san)}</b> · أفضل بديل: <b>${esc(entry.best_san||'—')}</b></p>
   <p>التقييم بعد النقلة من منظور الأبيض: ${ev} · تراجع تقديري في الأفضلية: ${entry.loss_cp==null?'غير محسوب':(Number(entry.loss_cp)/100).toFixed(2)+' من قيمة البيدق'}</p>
   ${entry.book_name?`<p>▣ من قاعدة الافتتاحات المحلية: ${esc(entry.book_name)}</p>`:''}
   <p>${explainMove(entry)}</p><button class="primary" type="button" data-v7-open="review">اسأل المعلّم</button><details class="analysis-extra"><summary>شرح المحرك المحفوظ</summary><button class="outline" type="button" data-review-teacher="1">عرض الشرح التفصيلي</button></details></div>`;
 refreshReviewTeacherStep();
 $('scenarios').innerHTML=entry.lines?.length?'<details class="analysis-extra"><summary>استكشف بدائل المحرك</summary>'+entry.lines.map((l,i)=>`<button class="scenario-card" data-line="${i}"><strong>البديل ${i+1}: ${esc(l.san)}</strong> · ${(Number(l.eval)/100).toFixed(2)}
  <small>${esc((l.line||[]).join(' · '))} · عمق ${esc(l.depth||'—')}</small></button>`).join('')+'</details>':'<p class="muted">السيناريوهات تظهر بعد اكتمال التحليل العميق.</p>';
}
$('move-detail').addEventListener('click',async e=>{
 if(!e.target.closest('[data-review-teacher]')||!S.review||!S.ply)return;
 const target=$('review-teacher'),gid=S.review.id,ply=S.ply,token=S.reviewTeacherToken=(S.reviewTeacherToken||0)+1;
 target.hidden=false;target.textContent='جارٍ إعداد شرح يعتمد على وضعية الرقعة...';
 try{
  const data=await request('/games/'+gid+'/coach/'+ply);
  if(S.reviewTeacherToken!==token||S.review?.id!==gid||S.ply!==ply)return;
  S.reviewTeacherPlan=data;
  target.innerHTML=`<div class="teacher-section"><h3>ماذا تلاحظ قبل النقلة؟</h3>${teacherList(data.position.observations)}
   <h3>ما الأسئلة المهمة هنا؟</h3>${teacherList(data.position.questions)}</div>
   <div class="teacher-section"><h3>الدرس من هذه النقلة</h3><p>${esc(data.takeaway)}</p><p>${esc(data.comparison)}</p>
   <p>اضغط على أي سيناريو معروض أعلاه لتشغيله على الرقعة، ثم استخدم «الخطوة التالية» لقراءة النقلة داخل الوضع.</p></div>
   <details class="teacher-glossary"><summary>شرح مصطلحات التحليل</summary>${teacherList(Object.values(data.terminology))}</details>
   <p class="tiny muted">${esc(data.notice)}</p><div id="review-teacher-step" class="teacher-section"></div>`;
  refreshReviewTeacherStep();
 }catch(err){if(token===S.reviewTeacherToken)target.textContent=err.message;}
});
function refreshReviewTeacherStep(){
 const target=$('review-teacher-step'),plan=S.reviewTeacherPlan;
 if(!target||!plan)return;
 if(S.practicing){target.innerHTML='<p>متابعة حرة من هذا الموضع؛ العب النقلات القانونية للطرفين وقارن بنفسك.</p>';return;}
 if(!S.scenario){target.innerHTML='<p>اختر سيناريو من القائمة لتشاهد لماذا يغيّر كل ردّ شكل الموقف على الرقعة.</p>';return;}
 const first=S.scenario.moves?.[0];
 const line=plan.scenarios?.find(x=>x.moves?.[0]===first);
 if(!line){target.innerHTML='<p>لا يتوفر تفسير تفصيلي محفوظ لهذا السيناريو؛ راقب النقلات المعروضة على الرقعة.</p>';return;}
 const n=S.scenarioStep;
 if(!n){target.innerHTML='<p>شاهد السهم في السيناريو ثم اضغط «الخطوة التالية».</p>';return;}
 const step=line.steps[n-1];
 if(!step){target.textContent='هذه النقلة لم تدخل في التحليل المحفوظ.';return;}
 target.innerHTML=`<h3>${esc(step.summary)}</h3><h4>الفوائد الظاهرة في الموقف</h4>${teacherList(step.benefits)}
   <h4>التهديدات والمخاطر</h4>${teacherList(step.risks)}`;
}
function explainMove(m){const g=m.grade;
 if(g==='book')return 'النقلة تتطابق مع تسلسل معروف في قاعدة الافتتاحات المحلية. هدف الدراسة هو فهم الفكرة وليس حفظ النقلات وحدها.';
 if(g==='blunder')return `هذه النقلة سببت خسارة تقديرية كبيرة في التقييم. قبل تكرارها افحص سلامة الملك والقطع غير المحمية. قارن الخط الأول بنقلتك ${m.san}.`;
 if(g==='missed')return `ضاعت فرصة مهمة للحصول على أفضلية. افحص التهديدات القسرية، وجرّب بدء السيناريو الأول ثم قارن رد الخصم.`;
 if(g==='mistake')return `يوجد بديل أقوى في هذا الموضع، وهو ${m.best_san||'أحد خطوط المحرك'}. استخدم الخطوط المعروضة لمعرفة التطور المتوقع.`;
 if(g==='weak')return `النقلة قانونية لكنها أقل كفاءة من ${m.best_san||'أفضل خط'}. جرب الانتقال إلى السيناريوهات وقارن النشاط والمادة.`;
 if(g==='excellent')return 'اختيار قوي ومتوافق مع أفضلية المحرك. لاحظ كيف يمكن متابعة الخطة في الخط الأول.';
 return 'راجع أفضل استمراريات المحرك وقارن مواقف القطع بعد كل رد.';
}
function goPly(i){if(!S.review)return;S.teacherArrow=null;S.reviewTeacherToken=(S.reviewTeacherToken||0)+1;S.reviewTeacherPlan=null;$('review-teacher').hidden=true;S.ply=Math.max(0,Math.min(S.review.moves.length,i));S.scenario=null;S.scenarioStep=0;S.practicing=false;S.selected=null;drawReview();}
$('first-move').onclick=()=>goPly(0);
$('prev-move').onclick=()=>goPly(S.ply-1);$('next-move').onclick=()=>goPly(S.ply+1);$('last-move').onclick=()=>goPly(S.review?.moves.length||0);
$('flip-board').onclick=()=>{S.flip=!S.flip;drawReview();};
$('moves').addEventListener('click',e=>{const m=e.target.closest('[data-ply]');if(m)goPly(Number(m.dataset.ply));});
$('scenarios').addEventListener('click',async e=>{const m=e.target.closest('[data-line]');if(!m||!S.review)return;
 try{S.scenario=await request('/games/'+S.review.id+'/scenario/'+S.ply+'/'+m.dataset.line);
 S.scenario.rootPly=S.ply-1;S.scenarioStep=0;S.practicing=false;S.selected=null;
 $('scenario-title').textContent='سيناريو '+(Number(m.dataset.line)+1)+' · '+S.scenario.san.join(' · ');
 drawReview();}catch(error){toast(error.message);}});
$('scenario-prev').onclick=()=>{if(!S.scenario||S.practicing)return;S.scenarioStep=Math.max(0,S.scenarioStep-1);drawReview()};
$('scenario-next').onclick=()=>{if(!S.scenario||S.practicing)return;S.scenarioStep=Math.min(S.scenario.moves.length,S.scenarioStep+1);drawReview()};
$('scenario-play').onclick=()=>{if(!S.scenario)return;S.scenarioStep=S.scenario.moves.length;drawReview();};
$('scenario-practice').onclick=async()=>{if(!S.scenario||!S.review)return;
 S.practicing=true;S.practiceTrail=S.scenario.moves.slice(0,S.scenarioStep);
 S.scenario.practiceFen=S.scenario.fens[S.scenarioStep];
 try{const d=await getLegalPractice();S.scenario.legalMoves=d.legal_moves;drawReview();toast('أكمل من هذا الموضع، بالسحب أو النقر');}
 catch(e){toast(e.message);}};
$('exit-scenario').onclick=()=>{S.scenario=null;S.practicing=false;S.selected=null;drawReview();};
async function getLegalPractice(){
 return request('/games/'+S.review.id+'/practice?root_ply='+S.scenario.rootPly+
   '&trail='+encodeURIComponent(S.practiceTrail.join(',')));
}

function reviewClick(sq){if(!S.practicing||!S.scenario)return;
 const poss=S.scenario.legalMoves||[];
 if(S.selected===sq){S.selected=null;drawReview();return;}
 if(S.selected){const match=poss.filter(m=>m.startsWith(S.selected+sq));if(match.length){window.ChessBoardPro.promotion(match,doPractice);return;}}
 if(poss.some(m=>m.startsWith(sq))){S.selected=sq;drawReview();}}
function reviewDrop(from,to){if(!S.practicing||!S.scenario)return;const match=(S.scenario.legalMoves||[]).filter(x=>x.startsWith(from+to));window.ChessBoardPro.promotion(match,doPractice);}
async function doPractice(uci){const trail=[...S.practiceTrail];try{const d=await request('/games/'+S.review.id+'/practice',{method:'POST',body:{root_ply:S.scenario.rootPly,trail,uci}});
 S.practiceTrail.push(uci);S.scenario.practiceFen=d.fen;S.scenario.legalMoves=d.legal_moves;S.selected=null;drawReview();
 if(d.ended)toast('وصلت إلى وضعية نهائية في التدريب.');}catch(e){if(e.name!=='AbortError')toast(e.message);}}
async function loadCourse(){try{const d=await request('/course');const rating=d.current_rating;
 const target=d.target_rating,remaining=d.rating_gap;
 const milestones=[700,1000,1200,1500,1800,2000,2400].filter(x=>x<=Math.max(target,1500));
 $('rating-path').innerHTML=`<div class="between"><h2>مسار التقدم في ${esc(d.rating_format.toUpperCase())}</h2><span>${esc(rating??'لم يصل التصنيف')} → ${esc(target)}</span></div><progress class="progress" max="100" value="${rating?Math.min(100,rating/target*100):0}"></progress><p>الهدف: ${target} · الفارق الحالي: ${remaining??'بانتظار بيانات Chess.com'} نقطة.
  محورك الحالي من التحليل: <b>${esc(d.improvement_focus||'بانتظار نتائج التحليل')}</b>.</p><div class="filter-row">${milestones.map(x=>`<span class="grade-tag grade-${rating!==null&&rating>=x?'excellent':'unrated'}">${x}${rating!==null&&rating>=x?' ✓':''}</span>`).join('')}</div><p class="tiny muted">اجتياز الدروس لا يغيّر تصنيف Chess.com تلقائياً؛ التصنيف يتغيّر عبر نتائج مبارياتك المصنفة الفعلية.</p>`;
 $('course-list').innerHTML=[1,2,3].map(stage=>`<h2 class="stage-heading">المرحلة ${stage}</h2>`+d.lessons.filter(l=>l.stage===stage).map(l=>`<div class="lesson-card ${l.unlocked||l.passed?'':'locked'}"><div><strong>الدرس ${l.id}: ${esc(l.title)}</strong><small>${esc(l.goal)} · ${l.source_positions} وضعية من مبارياتك · ${l.solved}/${l.required} إجابات صحيحة</small></div><div><span>${l.passed?'✓ مجتاز':l.unlocked?'جاهز':'مقفل'}</span> <button data-start-lesson="${l.id}" ${l.unlocked||l.passed?'':'disabled'}> ${l.passed?'مراجعة':'ابدأ الدرس'} </button></div></div>`).join('')).join('');
 }catch(e){if(e.name!=='AbortError')toast(e.message);}}
$('course-list').addEventListener('click',e=>{const b=e.target.closest('[data-start-lesson]');if(b)openLesson(b.dataset.startLesson);});
async function openLesson(id){
 S.lessonSequence++;S.lessonMode='original';S.lessonPlan=null;S.lessonResult=null;S.lessonReveal=false;
 S.lessonScenarioIndex=-1;S.lessonStep=0;S.lessonPracticeTrail=[];S.lessonPracticeFen=null;S.lessonPracticeLegal=[];
 try{
  S.lesson=await request('/course/'+id+'?side='+encodeURIComponent(S.lessonSide));
  S.lessonSelect=null;S.lessonHintArrow=null;$('lesson').hidden=false;
  const p=S.lesson.position;
  $('lesson-title').textContent=S.lesson.lesson.title+' · '+S.lesson.lesson.solved+'/'+S.lesson.lesson.required;
  $('lesson-info').textContent=`${S.lesson.lesson.goal}. تلعب ${p.player_color==='white'?'بالأبيض':'بالأسود'} في المباراة المنتهية ${p.white} × ${p.black}. فكّر في النقلة قبل كشف الحل.`;
  $('lesson-feedback').textContent='قبل تحريك أي قطعة، اقرأ شرح الموقف والأسئلة التعليمية. ليس الهدف تخمين نقلة واحدة.';
  $('lesson-coach-overview').textContent='جارٍ استخراج الوقائع من وضعية المباراة...';
  drawLesson();refreshLessonCoach();$('lesson').scrollIntoView({behavior:'smooth',block:'start'});
  try{
   const plan=await request('/course/'+id+'/coach?game_id='+p.game_id+'&ply='+p.ply);
   if(S.lesson?.lesson.id===id && S.lesson?.position.game_id===p.game_id && S.lesson?.position.ply===p.ply){
    S.lessonPlan=plan;refreshLessonCoach();drawLesson();
   }
  }catch(e){$('lesson-coach-overview').textContent='شرح هذا الموقف غير جاهز: '+e.message;}
 }catch(e){S.lesson=null;$('lesson').hidden=true;toast(e.message);}
}
function lessonScenario(){return S.lessonPlan?.scenarios?.[S.lessonScenarioIndex]||null;}
function lessonBoardState(){
 const p=S.lesson?.position;if(!p)return null;
 const sc=lessonScenario();
 if(S.lessonMode==='practice')return {fen:S.lessonPracticeFen,legalMoves:S.lessonPracticeLegal};
 if(S.lessonMode==='demo'&&sc)return {fen:sc.fens[S.lessonStep],legalMoves:[]};
 return {fen:p.fen,legalMoves:p.legal_moves};
}
function drawLesson(){
 const p=S.lesson?.position,bs=lessonBoardState();if(!p||!bs)return;
 const sc=lessonScenario();
 const allowed=bs.legalMoves||[];
 const targets=S.lessonSelect?allowed.filter(x=>x.startsWith(S.lessonSelect)).map(x=>x.slice(2,4)):[];
 const oriented=p.player_color;
 let arrow=S.lessonHintArrow;
 let last=null;
 if(S.lessonMode==='demo'&&sc){
  last=S.lessonStep?sc.moves[S.lessonStep-1]:null;
  arrow=S.lessonStep<sc.moves.length?sc.moves[S.lessonStep]:null;
 }
 if(S.lessonMode==='practice'){arrow=null;last=S.lessonPracticeTrail.at(-1)||null;}
 window.ChessBoardPro.render($('lesson-board'),bs.fen,oriented,{hintArrow:arrow,hintArrows:S.lessonMode==='original'?(S.lessonPlan?.position?.arrows||[]).map(x=>({uci:x.uci,color:'#f17373'})):[],last:last?[last.slice(0,2),last.slice(2,4)]:[],lastUci:last,
  selected:S.lessonSelect,targets,legalMoves:allowed,onClick:lessonClick,onMove:lessonDrop});
 $('lesson-step-counter').textContent=S.lessonMode==='demo'&&sc?`${S.lessonStep} من ${sc.moves.length} نصف نقلة`:
   S.lessonMode==='practice'?`متابعة حرة · ${S.lessonPracticeTrail.length} نقلة`:'الموقف الأصلي';
}
function lessonClick(sq){
 if(!S.lesson||S.busy||S.lessonMode==='demo')return;
 const allowed=lessonBoardState()?.legalMoves||[];
 if(S.lessonSelect===sq){S.lessonSelect=null;drawLesson();return;}
 if(S.lessonSelect){const match=allowed.filter(x=>x.startsWith(S.lessonSelect+sq));if(match.length){window.ChessBoardPro.promotion(match,S.lessonMode==='practice'?lessonPracticeStep:lessonAttempt);return;}}
 if(allowed.some(x=>x.startsWith(sq))){S.lessonSelect=sq;drawLesson();}
}
function lessonDrop(from,to){
 if(!S.lesson||S.busy||S.lessonMode==='demo')return;
 const allowed=lessonBoardState()?.legalMoves||[];
 window.ChessBoardPro.promotion(allowed.filter(x=>x.startsWith(from+to)),S.lessonMode==='practice'?lessonPracticeStep:lessonAttempt);
}
const teacherList=(arr,cls='')=>'<ul class="teacher-bullets '+cls+'">'+(arr||[]).map(x=>`<li>${esc(x)}</li>`).join('')+'</ul>';
function refreshLessonCoach(){
 const plan=S.lessonPlan;if(!S.lesson)return;
 $('lesson-next').hidden=!S.lessonResult?.correct;
 $('lesson-view-original').hidden=S.lessonMode==='original';
 $('lesson-play').disabled=S.lessonMode==='practice'||!lessonScenario();
 $('lesson-step-back').disabled=S.lessonMode!=='demo'||S.lessonStep<=0;
 $('lesson-step-forward').disabled=S.lessonMode!=='demo'||!lessonScenario()||S.lessonStep>=lessonScenario().moves.length;
 $('lesson-next').textContent=S.lessonResult?.passed?'العودة إلى المراحل بعد اجتياز الدرس':'الموقف التالي بعد المراجعة';
 if(!plan){$('lesson-coach-overview').textContent='المعلومات التعليمية غير متاحة بعد. يمكنك تجربة الحركة ومراجعة النتيجة.';return;}
 const ob=plan.position;
 $('lesson-coach-overview').innerHTML=`<h3>اقرأ الموقف قبل أن تتحرك</h3>${teacherList(ob.observations)}<h3>أسئلة تفكير</h3>${teacherList(ob.questions)}
  <p class="tiny muted">هذه ملاحظات مثبتة على وضعية الرقعة، وليست ادعاءً أن كل كش أو أسر هو الأفضل.</p>`;
 $('lesson-teaching-after').hidden=!S.lessonReveal;
 $('lesson-case-controls').hidden=!S.lessonReveal;
 if(!S.lessonReveal)return;
 const compared=S.lessonResult?.move_teaching;
 $('lesson-teaching-after').innerHTML=`<h3>لماذا هذه النقلة؟</h3>
 <p>${esc(plan.takeaway)}</p><p><strong>المقارنة مع نقلة المباراة:</strong> ${esc(plan.comparison)}</p>
 ${compared?`<div class="teacher-section"><h4>نقلتك التي جربتها: ${esc(compared.san)}</h4>
 <strong>الفوائد المؤكدة في الرقعة</strong>${teacherList(compared.benefits)}
 <strong>المخاطر التي يجب حسابها</strong>${teacherList(compared.risks)}</div>`:''}
 <details class="teacher-glossary"><summary>ما معنى التقييم وفارق الأفضلية؟</summary>${teacherList(Object.values(plan.terminology))}</details>
 <p class="tiny muted">${esc(plan.notice)}</p>`;
 $('lesson-scenario-choices').innerHTML=plan.scenarios?.length?plan.scenarios.map((sc,i)=>`<button type="button" class="teacher-scenario ${i===S.lessonScenarioIndex?'active':''}" data-teacher-scenario="${i}">
 <strong>${esc(sc.label)} · ${esc(sc.steps[0]?.san||'—')}</strong>
 <small>${esc(sc.evaluation)}</small><small>${esc(sc.source_note)}</small></button>`).join(''):'<p class="muted">لم تُحفظ خطوط متابعة لهذا الموقف. لن نختلق سيناريوهات غير محللة.</p>';
 const sc=lessonScenario();
 $('lesson-case-title').textContent=sc?sc.label:'اختر سيناريو لعرضه على الرقعة';
 $('lesson-play').disabled=!sc||S.lessonMode==='practice';
 $('lesson-step-back').disabled=S.lessonMode!=='demo'||S.lessonStep<=0;
 $('lesson-step-forward').disabled=S.lessonMode!=='demo'||!sc||S.lessonStep>=sc.moves.length;
 $('lesson-step-info').innerHTML=sc?(S.lessonMode==='practice'?'<p>أنت الآن في وضع متابعة حرة للطرفين. النقلات تُراجع قانونياً ولا يقدم المحرك خصماً في هذا الوضع.</p>':
  S.lessonStep===0?`<p>راقب السهم ثم اضغط «النقلة التالية». هذا السيناريو محفوظ من المباراة أو من Stockfish.</p><p>${esc(sc.source_note)}</p>`:
  `<div class="teacher-section"><strong>${esc(sc.steps[S.lessonStep-1]?.summary)}</strong><h4>ما الذي تحقّقه النقلة؟</h4>
  ${teacherList(sc.steps[S.lessonStep-1]?.benefits)}<h4>المخاطر وردود الخصم</h4>${teacherList(sc.steps[S.lessonStep-1]?.risks)}</div>`):
  '<p>اختر سيناريو من القائمة لبدء الشرح المصور.</p>';
}
async function lessonAttempt(uci){
 if(S.busy||!S.lesson||S.lessonMode!=='original')return;S.busy=true;
 const snapshot=S.lesson,p=snapshot.position;
 try{
  const d=await request('/course/'+snapshot.lesson.id+'/attempt',{method:'POST',body:{uci,game_id:p.game_id,ply:p.ply}});
  S.lessonResult=d;S.lessonReveal=true;S.lessonSelect=null;
  $('lesson-feedback').innerHTML=`<strong>${d.correct?'✓ إجابة قوية تم قبولها':'هذه النقلة لم تُقبل كحل الدرس'}</strong>
  <p>${esc(d.explanation)}</p>${d.correct?`<p>التقدم: ${d.solved} / ${d.required} مواقف صحيحة.</p>`:''}
  <p>لا ننقلك إلى التمرين التالي حتى تفهم المقارنة وتعرض السيناريوهات بنفسك.</p>`;
  refreshLessonCoach();drawLesson();if(d.correct)loadCourse();
 }catch(e){toast(e.message);}finally{S.busy=false;}
}
function chooseLessonScenario(index){
 const sc=S.lessonPlan?.scenarios?.[index];if(!sc)return;
 S.lessonSequence++;S.lessonReveal=true;S.lessonScenarioIndex=index;S.lessonStep=0;S.lessonMode='demo';S.lessonSelect=null;S.lessonHintArrow=null;
 drawLesson();refreshLessonCoach();
}
$('lesson-scenario-choices').addEventListener('click',e=>{const item=e.target.closest('[data-teacher-scenario]');if(item)chooseLessonScenario(Number(item.dataset.teacherScenario));});
$('lesson-step-forward').onclick=()=>{
 const sc=lessonScenario();if(S.lessonMode!=='demo'||!sc||S.lessonStep>=sc.moves.length)return;
 S.lessonStep++;drawLesson();refreshLessonCoach();
};
$('lesson-step-back').onclick=()=>{if(S.lessonMode!=='demo'||S.lessonStep<=0)return;S.lessonStep--;drawLesson();refreshLessonCoach();};
$('lesson-play').onclick=async()=>{
 if(!lessonScenario())return;
 if(S.lessonMode==='original'){chooseLessonScenario(S.lessonScenarioIndex);}
 const token=++S.lessonSequence,sc=lessonScenario();
 while(S.lessonMode==='demo'&&S.lessonStep<sc.moves.length&&S.lessonSequence===token){
  S.lessonStep++;drawLesson();refreshLessonCoach();
  await new Promise(r=>setTimeout(r,730));
 }
};
$('lesson-case-continue').onclick=async()=>{
 const sc=lessonScenario(),p=S.lesson?.position;if(!sc||!p)return;
 S.lessonSequence++;S.lessonPracticeTrail=sc.moves.slice(0,S.lessonStep);
 try{
  const root=Math.max(0,p.ply-1),trail=S.lessonPracticeTrail.join(',');
  const d=await request('/games/'+p.game_id+'/practice?root_ply='+root+'&trail='+encodeURIComponent(trail));
  S.lessonPracticeFen=d.fen;S.lessonPracticeLegal=d.legal_moves;S.lessonMode='practice';S.lessonSelect=null;
  drawLesson();refreshLessonCoach();toast('وضع متابعة حرة: حرّك قطع أي طرف لاختبار الفكرة.');
 }catch(e){toast(e.message);}
};
async function lessonPracticeStep(uci){
 const p=S.lesson?.position;if(!p||S.lessonMode!=='practice'||S.busy)return;S.busy=true;
 try{
  const d=await request('/games/'+p.game_id+'/practice',{method:'POST',body:{root_ply:p.ply-1,trail:S.lessonPracticeTrail,uci}});
  S.lessonPracticeTrail.push(uci);S.lessonPracticeFen=d.fen;S.lessonPracticeLegal=d.legal_moves;S.lessonSelect=null;
  drawLesson();refreshLessonCoach();if(d.ended)toast('الموقف وصل إلى نهاية قانونية.');
 }catch(e){toast(e.message);}finally{S.busy=false;}
}
$('lesson-view-original').onclick=()=>{
 S.lessonSequence++;S.lessonMode='original';S.lessonSelect=null;S.lessonHintArrow=null;drawLesson();refreshLessonCoach();
};
$('lesson-reveal').onclick=()=>{
 if(!S.lesson)return;
 S.lessonReveal=true;S.lessonHintArrow=S.lesson.position.best_uci;refreshLessonCoach();drawLesson();
};
$('lesson-hint').onclick=()=>{
 if(!S.lesson)return;
 S.lessonSequence++;S.lessonMode='original';S.lessonReveal=true;S.lessonHintArrow=S.lesson.position.best_uci||null;
 S.lessonSelect=null;drawLesson();refreshLessonCoach();
 $('lesson-feedback').textContent=`شاهد السهم الأخضر: ${S.lesson.position.best_san||'الخط الأقوى المحفوظ'}. افتح السيناريوهات لفهم ردود الخصم بدل حفظ النقلة.`;
};
$('lesson-retry').onclick=()=>{
 S.lessonSequence++;S.lessonMode='original';S.lessonSelect=null;S.lessonHintArrow=null;S.lessonResult=null;
 S.lessonScenarioIndex=-1;S.lessonStep=0;S.lessonReveal=false;
 drawLesson();refreshLessonCoach();$('lesson-feedback').textContent='اختر نقلة من جديد بعد دراسة الموقف، ثم اطلب الشرح المفصّل.';
};
$('lesson-next').onclick=()=>{
 if(!S.lessonResult?.correct||!S.lesson)return;
 if(S.lessonResult.passed){$('lesson').hidden=true;S.lesson=null;loadCourse();return;}
 openLesson(S.lesson.lesson.id);
};
$('close-lesson').onclick=()=>{S.lessonSequence++;$('lesson').hidden=true;S.lesson=null;S.lessonPlan=null;};
$('lesson-side').addEventListener('change',e=>{S.lessonSide=e.target.value;if(S.lesson)openLesson(S.lesson.lesson.id);});
function showSettings(){loadAnalysisSpeed();const m=S.me;$('account-email').textContent=m.email;$('chess-username').value=m.chess_username||'';
 $('target-rating').value=m.target_rating;$('rating-format').value=m.rating_format;
 $('theme').value=m.theme;$('board-theme').value=m.board_theme;}
async function saveSettings(silent=false){const data={chess_username:$('chess-username').value.trim(),theme:$('theme').value,
 board_theme:$('board-theme').value,target_rating:Number($('target-rating').value),rating_format:$('rating-format').value};
 try{const d=await request('/settings',{method:'PUT',body:data});S.me=await request('/me');setTheme(S.me.theme);document.body.dataset.board=S.me.board_theme;
 $('current-player').textContent=S.me.chess_username||'لم يُربط حساب Chess.com';if(!silent)toast(d.archive_reimport==='pending'?'حُفظت الإعدادات. يبدأ الاستيراد الجديد في الخلفية.':'تم حفظ الإعدادات');}
 catch(e){toast(e.message);}}
$('settings-form').addEventListener('submit',e=>{e.preventDefault();saveSettings();});
const ANALYSIS_SPEED_PRESETS={turbo:[1,1],fast:[3,2],balanced:[10,2],detailed:[30,3],deep:[120,3]};
function speedSummary(speed,queue={}){
 const el=$('analysis-speed-summary');if(!el||!speed)return;
 let message=`السرعة الفعلية: ${Number(speed.seconds)} ثانية لكل وضعية، ${Number(speed.multipv)} خط/خطوط · الحد العام: ${Number(speed.server_seconds_cap)} ثانية.`;
 if(speed.limited_by_admin)message+=' الحدّ العام يقلل الإعداد المطلوب.';
 if(speed.worker_paused)message+=' ⏸ العامل متوقف مؤقتاً من الإدارة.';
 const pending=Number(queue.pending||0),running=Number(queue.running||0);
 message+=` · قيد الانتظار: ${pending} · قيد التحليل: ${running}`;
 el.textContent=message;
}
async function loadAnalysisSpeed(){
 const el=$('analysis-speed-summary');el.textContent='جارٍ تحميل سرعة التحليل...';
 try{const data=await request('/analysis/speed');$('analysis-speed').value=data.speed.preset;speedSummary(data.speed,data.queue);}
 catch(error){el.textContent='تعذر قراءة السرعة: '+error.message;}
}
$('analysis-speed-form').addEventListener('submit',async event=>{
 event.preventDefault();const btn=$('save-analysis-speed');btn.disabled=true;
 try{const data=await request('/analysis/speed',{method:'PUT',body:{preset:$('analysis-speed').value}});
 speedSummary(data.speed);toast('حُفظت سرعة التحليل. يعمل الإعداد الجديد مع الوضعية التالية.');await loadAnalysisSpeed();}
 catch(error){toast('تعذر حفظ السرعة: '+error.message);}
 finally{btn.disabled=false;}
});
$('analysis-speed').addEventListener('change',()=>{
 const selected=$('analysis-speed').value;
 if(!ANALYSIS_SPEED_PRESETS[selected])return;
 const [sec,pv]=ANALYSIS_SPEED_PRESETS[selected];
 $('analysis-speed-summary').textContent=`المطلوب: ${sec} ثانية و${pv} خط/خطوط لكل وضعية. اضغط حفظ للتطبيق؛ حد الخادم قد يقلل هذه القيم.`;
});
$('password-form').addEventListener('submit',async e=>{e.preventDefault();try{await request('/password',{method:'POST',body:{current_password:$('old-pass').value,new_password:$('new-pass').value}});toast('تم تغيير كلمة المرور. الرجاء تسجيل الدخول من جديد.');S.me=null;showAuth();}catch(err){toast(err.message);}});
$('delete-account').onclick=async()=>{if(!confirm('هل تريد حذف حسابك وجميع بياناته نهائياً؟'))return;
 if(!confirm('تأكيد أخير: لن يمكن استعادة بيانات المنصة الجديدة.'))return;
 try{await request('/account',{method:'DELETE'});S.me=null;showAuth();}catch(e){if(e.name!=='AbortError')toast(e.message);}};
async function loadAdmin(){if(window.loadControl)return window.loadControl();return loadLegacyAdmin();}
async function loadLegacyAdmin(){try{const [o,u]=await Promise.all([request('/admin/overview'),request('/admin/users')]);
 const c=o.config;$('deep-seconds').value=c.deep_seconds;$('multipv').value=c.multipv;
 updateAdminSpeedPreset();
 $('archive-refresh').value=c.archive_refresh_hours;$('max-games').value=c.max_games_per_user;if($('teacher-platform-limit'))$('teacher-platform-limit').value=c.teacher_daily_limit||20;
 $('pause-worker').checked=c.worker_paused==='true';$('registration-open').checked=c.registration_open==='true';
 $('admin-overview').innerHTML=`<p>المستخدمون: <strong>${o.users}</strong> · المباريات: <strong>${o.games}</strong></p>`+o.jobs.map(x=>`<p>${esc(x.stage)}: ${x.n}</p>`).join('');
 $('admin-users').innerHTML='<h3>الحسابات المسجلة</h3>'+u.users.map(x=>`<div class="between"><p>${esc(x.email)} · ${esc(x.chess_username||'غير مربوط')} · ${x.games} مباراة</p>${x.role==='admin'?'':`<button data-admin-uid="${Number(x.id)}" data-admin-disabled="${x.disabled?0:1}">${x.disabled?'تفعيل':'تعطيل'}</button>`}</div>`).join('');
 }catch(e){if(e.name!=='AbortError')toast(e.message);}}
function updateAdminSpeedPreset(){
 const seconds=Number($('deep-seconds').value),lines=Number($('multipv').value);
 const match=Object.entries(ANALYSIS_SPEED_PRESETS).find(([,vals])=>vals[0]===seconds&&vals[1]===lines);
 $('admin-speed-preset').value=match?.[0]||'custom';
}
$('admin-speed-preset').addEventListener('change',()=>{
 const pair=ANALYSIS_SPEED_PRESETS[$('admin-speed-preset').value];
 if(pair){$('deep-seconds').value=pair[0];$('multipv').value=pair[1];}
});
$('deep-seconds').addEventListener('input',updateAdminSpeedPreset);
$('multipv').addEventListener('input',updateAdminSpeedPreset);
$('admin-form').addEventListener('submit',async e=>{e.preventDefault();try{await request('/admin/settings',{method:'PUT',body:{deep_seconds:Number($('deep-seconds').value),multipv:Number($('multipv').value),
 archive_refresh_hours:Number($('archive-refresh').value),max_games_per_user:Number($('max-games').value),worker_paused:$('pause-worker').checked,registration_open:$('registration-open').checked,teacher_daily_limit:Number($('teacher-platform-limit')?.value||20)}});toast('حُفظت إعدادات السيرفر');}catch(err){toast(err.message);}});
boot();

$('admin-users').addEventListener('click',async e=>{
 const b=e.target.closest('[data-admin-uid]');if(!b)return;
 if(!confirm('تأكيد تغيير حالة الحساب؟'))return;
 try{await request('/admin/users/'+b.dataset.adminUid,{method:'PATCH',body:{disabled:b.dataset.adminDisabled==='1'}});
   toast('تم تحديث حالة الحساب');await loadAdmin();}catch(err){toast(err.message);}
});
