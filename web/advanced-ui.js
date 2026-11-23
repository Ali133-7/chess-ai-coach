/* V3: per-game analytics, progress trends, and issue remediation. */
'use strict';
(function(){
 const metric=(n,label)=>`<div class="metric"><strong>${esc(n??'—')}</strong><small>${esc(label)}</small></div>`;
 const qlabels={best:'ممتازة',brilliant:'مدهشة',excellent:'ممتازة',good:'جيدة',inaccuracy:'ضعيفة',weak:'ضعيفة',missed:'ضياع فرصة',mistake:'خطأ',blunder:'خطأ فادح'};
 const phlabels={opening:'الافتتاح',middlegame:'وسط اللعب',endgame:'النهايات'};
 function lineGraph(points,{xKey='ply',yKey='white_win_chance',min=0,max=100}={}){
  if(!points.length)return '<p class="muted">المباراة تحتاج إعادة تحليل لعرض الرسم البياني.</p>';
  const W=760,H=180,pad=16, x=p=>pad+(W-pad*2)*(p/(Math.max(1,points.length-1))), y=v=>H-pad-((Math.max(min,Math.min(max,v))-min)/(max-min))*(H-pad*2);
  const path=points.map((p,i)=>(i?'L':'M')+x(i).toFixed(2)+' '+y(Number(p[yKey]??50)).toFixed(2)).join(' ');
  return `<svg class="analysis-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="رسم بياني لتطور أفضلية الأبيض خلال المباراة">`+
    [25,50,75].map(n=>`<path d="M${pad} ${y(n)} H${W-pad}" stroke="#5b6c83" opacity=".32" stroke-dasharray="4 6"/><text x="${W-31}" y="${y(n)-5}" fill="#96a4b8" font-size="11">${n}%</text>`).join('')+
    `<path d="${path}" fill="none" stroke="#37d6c8" stroke-width="3" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>`+
    `<circle cx="${x(points.length-1)}" cy="${y(Number(points.at(-1)[yKey]??50))}" r="4" fill="#f3d68d"/></svg>`;
 }
 function phaseStats(phases){
  if(!phases||!Object.keys(phases).length)return '<p class="muted tiny">أعد تحليل المباراة لإظهار تقييم كل مرحلة.</p>';
  return '<div class="phase-breakdown">'+Object.entries(phases).map(([k,v])=>`<div class="phase-row"><span>${phlabels[k]||esc(k)}</span><strong>${v.accuracy??'—'}%</strong><small>${v.moves} نقلة · ${v.errors} أخطاء · ACPL ${v.acpl??'—'}</small></div>`).join('')+'</div>';
 }
 function review(r){
  if(!r)return;
  const legacy=r.accuracy_estimate==null;
  $('review-kpis').innerHTML=metric(legacy?'—':r.accuracy_estimate+'%','دقة تقديرية')+
    metric(legacy?'—':r.average_centipawn_loss,'متوسط خسارة سنتي بيدق')+
    metric(r.errors,'فرصة تحسين')+
    metric(r.total_plies,'أنصاف نقلات');
  const evals=r.evaluation_graph||[];
  const comparison=r.players_comparison||{}, white=comparison.white,black=comparison.black;
  const versus=white&&black?`<div class="players-compare"><div><strong>${esc(r.white)}</strong><span>${white.accuracy??'—'}% · ACPL ${white.acpl??'—'}</span></div><div><strong>${esc(r.black)}</strong><span>${black.accuracy??'—'}% · ACPL ${black.acpl??'—'}</span></div></div>`:'';
  const timing=r.time_management?.average_think_seconds!=null?`<p class="muted tiny">متوسط وقت التفكير في نقلاتك: ${r.time_management.average_think_seconds} ثانية · نقلات مع أقل من 30 ثانية على الساعة: ${r.time_management.time_pressure_moves}</p>`:'';
  $('review-eval').innerHTML='<p class="muted tiny">احتمال فوز الأبيض تقديري حسب تقييم Stockfish؛ الرسم ليس من Chess.com.</p>'+lineGraph(evals)+versus+phaseStats(r.phases)+timing;
  if(legacy)$('review-lines').innerHTML='<p class="notice">هذه المباراة محفوظة بتحليل قديم. اضغط «إعادة التحليل» للحصول على مؤشرات الدقة والرسم البياني وخيارات المحرك المتعددة.</p>';
  else $('review-lines').innerHTML='<div class="quality-chips">'+Object.entries(r.quality_counts||{}).map(([k,v])=>`<span class="quality-chip ${k}">${qlabels[k]||k}: ${v}</span>`).join('')+'</div>';
 }
 function reviewPly(r,ply){
  if(!r||!$('review-lines'))return;
  const item=r.plies[ply];
  if(!item?.lesson){$('review-lines').innerHTML='<p class="muted tiny">اختر نقلة محللة من القائمة لعرض سيناريوهات Stockfish.</p>';return;}
  const l=item.lesson;
  const lines=l.top_lines||[];
  const title= `<h3 class="small-heading">النقلة ${item.move_number}${item.played_by==='white'?'.':'...'} ${esc(item.san)}</h3>`;
  const variants=l.scenarios||lines.map((ln,i)=>({rank:i+1,first:ln.san,moves:ln.line||[],pv_uci:ln.pv_uci||[],cp_white:ln.cp_white,summary:''}));
  const moves=variants.length?'<div class="engine-lines">'+variants.map((ln,i)=>`<div class="engine-line scenario-card"><span class="line-index">#${i+1}</span><strong>${esc(ln.first||'—')}</strong><code>${esc((ln.moves||[]).join(' → '))}</code><span>${ln.cp_white>0?'+':''}${(Number(ln.cp_white||0)/100).toFixed(2)}</span><p>${esc(ln.summary||'خط متوقع وفق تحليل المحرك لهذه الوضعية؛ النتائج مشروطة برد الخصم.')}</p>${ln.pv_uci?.length?`<button type="button" class="btn btn-small btn-primary" data-scenario="${i}">▶ اعرض الخط على الرقعة وأكمل اللعب</button>`:'<small>أعد تحليل المباراة بعمق لتفعيل تشغيل السيناريو.</small>'}</div>`).join('')+'</div>':'';
  const result=`<div class="move-metrics">${metric(l.move_accuracy!=null?l.move_accuracy+'%':'—','جودة النقلة تقديرية')}${metric(l.loss_cp,'خسارة سنتي بيدق')}</div>`;
  $('review-lines').innerHTML=title+result+moves+'<p class="muted tiny">هذه المؤشرات من تحليل المباراة المكتملة فقط؛ لا تُعرض تقييمات للمواقف المباشرة.</p>';
 }
 async function issues(){
  const target=$('issues-content');target.innerHTML='<p class="muted">جارٍ تحميل سجل الأخطاء...</p>';
  try{
   const filter=$('issues-filter').value,d=await api('/api/pro/v3/issues?limit=300&status='+encodeURIComponent(filter));
   const counts=d.counts||{};
   $('issues-summary').innerHTML=metric(counts.open||0,'مفتوحة')+metric(counts.practicing||0,'قيد التدريب')+metric(counts.resolved||0,'تمت المعالجة');
   target.innerHTML=d.issues.length?d.issues.map((item)=>`<article class="issue-card" data-gid="${esc(item.game_id)}" data-ply="${item.ply}">
     <div class="between"><strong>النقلة ${item.move_number}: ${esc(item.played)} ← الأفضل ${esc(item.best)}</strong><span class="quality-chip">${esc(item.quality)}</span></div>
     <p class="tiny muted">${esc(phlabels[item.phase]||item.phase)} · خسارة ${item.loss_cp} سنتي بيدق · تدريب ${item.solves}/${item.attempts} صحيح</p>
     <div class="issue-actions"><button class="btn btn-small btn-outline" data-issue-review="1">الموقف على الرقعة</button>
       <label>الحالة <select class="issue-status"><option value="open" ${item.status==='open'?'selected':''}>مفتوح</option><option value="practicing" ${item.status==='practicing'?'selected':''}>أتدرب عليه</option><option value="resolved" ${item.status==='resolved'?'selected':''}>تمت المعالجة</option></select></label>
       <button class="btn btn-small btn-primary" data-issue-save="1">حفظ</button></div>
     <textarea class="issue-notes" maxlength="500" rows="2" placeholder="ملاحظتي: لماذا حدث الخطأ؟ وما القاعدة التي سأطبقها؟">${esc(item.notes||'')}</textarea>
   </article>`).join(''):'<p class="muted">لا توجد أخطاء بهذه الحالة. رائع!</p>';
  }catch(e){target.innerHTML='<p class="error-text">'+esc(e.message)+'</p>';}
 }
 async function progress(){
  const target=$('progress-content');target.innerHTML='<p class="muted">جارٍ تحميل التقدم...</p>';
  try{
   const d=await api('/api/pro/v3/progress');
   const valid=d.trend.filter(x=>x.accuracy!=null);
   $('bulk-status').textContent=d.legacy_games?d.legacy_games+' مباراة بتحليل قديم تحتاج تحديثاً للحصول على مؤشرات الإصدار الثالث.':'كل المباريات المتاحة تستخدم المؤشرات الجديدة أو لم تُحفظ بعد.';
   target.innerHTML='<div class="metric-cards">'+metric(d.games_analyzed,'مباريات محللة')+metric(d.puzzles_attempted,'محاولات التمارين')+metric(d.puzzles_solved,'إجابات صحيحة')+metric(d.resolved_issues,'أخطاء تمت معالجتها')+'</div>'+
    '<h3 class="small-heading">الدقة التقديرية في المباريات المعاد تحليلها</h3>'+lineGraph(valid.map((x,i)=>({...x,ply:i,white_win_chance:x.accuracy})))+
    '<p class="muted tiny">لا تعكس هذه الأرقام تقييم Elo. مصدرها مقارنة نقلاتك بمحرك التحليل، وتختلف مع عمق البحث.</p>';
  }catch(e){target.innerHTML='<p class="error-text">'+esc(e.message)+'</p>';}
 }
 $('bulk-reanalysis').addEventListener('click',async()=>{
  const btn=$('bulk-reanalysis');busy(btn,true,'فحص العامل...');
  try{
   const d=await api('/api/pro/v5/deep/status');
   $('bulk-status').textContent=d.worker_ready?`التحليل العميق يعمل في الخلفية: ${d.completed||0} مكتمل و${d.waiting||0} منتظر. إغلاق المتصفح لا يوقفه. راجع الصفحة الرئيسية للمراقبة.`:'العامل العميق لم يبدأ بعد؛ تحقق من Docker.';
  }catch(e){notify(e.message);}finally{busy(btn,false);}
 });
 $('issues-filter').addEventListener('change',issues);
 $('issues-content').addEventListener('click',async e=>{
  const card=e.target.closest('.issue-card');if(!card)return;
  const gid=card.dataset.gid,ply=Number(card.dataset.ply);
  if(e.target.closest('[data-issue-review]')){
   setView('games');await openGame(gid);goReview(Math.max(0,ply-1));return;
  }
  const button=e.target.closest('[data-issue-save]');if(!button)return;
  busy(button,true,'حفظ...');
  try{await api('/api/pro/v3/issues/'+gid+'/'+ply,{method:'POST',body:{status:card.querySelector('.issue-status').value,notes:card.querySelector('.issue-notes').value}});
      notify('تم تحديث سجل الخطأ');await issues();
  }catch(err){notify(err.message);}finally{busy(button,false);}
 });
 $('review-lines').addEventListener('click',e=>{
  const button=e.target.closest('[data-scenario]');if(button)window.CoachScenario?.open(Number(button.dataset.scenario));
 });
 window.CoachAdvanced={review,reviewPly,issues,progress};
})();
