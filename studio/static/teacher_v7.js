/* Focused Arabic tutor: one composer, chronological replies, optional detail. */
'use strict';
(()=>{
 const states=new WeakMap();
 document.addEventListener('languagechange',()=>{document.querySelectorAll('.v7-tutor').forEach(panel=>{states.delete(panel);panel.querySelector('.v7-replies')?.replaceChildren();panel.classList.remove('has-replies');});});
 const names={groq:'Groq',xai:'Grok',openai:'OpenAI',openrouter:'OpenRouter'};
 function position(panel){
  if(panel.dataset.mode==='review')return S.review&&S.ply?{game_id:S.review.id,ply:S.ply}:null;
  const p=S.lesson?.position;return p?{game_id:p.game_id,ply:p.ply}:null;
 }
 function state(panel){
  if(!states.has(panel))states.set(panel,{key:'',thread_id:null,last:null,busy:false,provider:null});
  const s=states.get(panel),p=position(panel),key=p?`${p.game_id}:${p.ply}`:'';
  if(s.key!==key){s.key=key;s.thread_id=null;s.last=null;panel.querySelector('.v7-replies').replaceChildren();panel.classList.remove('has-replies');panel.querySelector('.v7-input').value='';}
  panel.querySelector('.v7-position').textContent=p?`نتحدث عن النقلة ${p.ply} فقط`:'اختر نقلة لنبدأ';
  return s;
 }
 function say(panel,text,error=false){const n=panel.querySelector('.v7-status');n.textContent=text;n.classList.toggle('error',error);}
 function provider(panel,data){const s=states.get(panel);if(s)s.provider=data.provider;panel.querySelector('.v7-provider').textContent=names[data.provider]||'المعلّم الذكي';}
 function addMessage(panel,role,html){
  const n=document.createElement('article');n.className='chat-message chat-'+role;
  n.innerHTML=html;panel.querySelector('.v7-replies').append(n);return n;
 }
 function render(panel,response,question){
  const s=state(panel);s.last=response;provider(panel,response);
  if(question)addMessage(panel,'user',`<p>${esc(question)}</p>`);
  const list=(items)=>`<ul>${(items||[]).slice(0,5).map(t=>`<li>${esc(t)}</li>`).join('')}</ul>`;
  const scenarios=response.scenarios||[],notes=new Map((response.scenario_notes||[]).map(n=>[n.scenario_id,n]));
  const detail=response.answer_kind==='general'?'':`<details class="chat-details"><summary>الفوائد والمخاطر والبدائل</summary><h4>الفوائد</h4>${list(response.benefits_ar)}<h4>انتبه إلى</h4>${list(response.risks_ar)}${scenarios.length?'<h4>شاهد البدائل على الرقعة</h4>':''}<div class="v7-lines">${scenarios.map((sc,i)=>`<button type="button" class="v7-line" data-v7-scenario="${i}"><strong>${esc((sc.san||[]).slice(0,4).join(' · '))}</strong><span>${esc(notes.get(sc.id)?.explanation_ar||'عرض نقلات المحرك')}</span></button>`).join('')}</div><p class="tiny muted">${esc(response.disclaimer||'')}</p></details>`;
  // Each response owns its scenarios, so earlier message buttons stay correct.
  const message=addMessage(panel,'assistant',`<span class="chat-author">المعلّم</span><h4>${esc(response.title_ar)}</h4><p>${esc(response.explanation_ar)}</p>${response.learning_question_ar?`<p class="chat-question">${esc(response.learning_question_ar)}</p>`:''}${detail}`);
  message._teacherResponse=response;panel.classList.add('has-replies');
  const transcript=panel.querySelector('.v7-replies');transcript.scrollTop=transcript.scrollHeight;
  panel.querySelector('.chat-empty')?.remove();
  say(panel,response.cached?'شرح محفوظ. يمكنك متابعة السؤال.':'يمكنك طرح سؤال متابعة.');
  panel.querySelector('.v7-input').focus({preventScroll:true});
 }
 async function action(panel,mode){
  const p=position(panel),s=state(panel);if(!p){say(panel,'اختر نقلة من مباراة مكتملة أولاً.',true);return;}if(s.busy)return;
  const input=panel.querySelector('.v7-input');const q=mode==='chat'?input.value.trim():window.I18n.t('اشرح هذه النقلة ببساطة، ثم اذكر أهم فكرة أتعلمها منها.');
  if(!q){input.focus();return;}
  const key=s.key;s.busy=true;panel.setAttribute('aria-busy','true');
  panel.querySelectorAll('[data-v7-ask],[data-v7-explain]').forEach(b=>b.disabled=true);
  say(panel,'المعلّم يقرأ الموقف…');
  try{
   const response=await request('/teacher/chat',{method:'POST',body:{...p,question:q,...(s.thread_id?{thread_id:s.thread_id}:{})}});
   const current=position(panel);if(states.get(panel)!==s||!current||`${current.game_id}:${current.ply}`!==key)return;
   s.thread_id=response.thread_id||null;if(mode==='chat')input.value='';
   render(panel,response,q);
  }catch(e){if(state(panel).key===key)say(panel,e.message,true);}
  finally{s.busy=false;panel.removeAttribute('aria-busy');panel.querySelectorAll('[data-v7-ask],[data-v7-explain]').forEach(b=>b.disabled=false);}
 }
 function playLine(panel,message,index){
  const response=message?._teacherResponse,s=state(panel),line=response?.scenarios?.[index],p=position(panel);if(!line?.moves?.length||!p)return;
  s.last=response;
  if(panel.dataset.mode==='review'){
   S.scenario={...line,rootPly:p.ply-1};S.scenarioStep=0;S.practicing=false;S.selected=null;S.teacherArrow=line.moves[0];drawReview();
  }else{
   S.lessonPlan={...(S.lessonPlan||{}),scenarios:response.scenarios};S.lessonScenarioIndex=index;S.lessonMode='demo';S.lessonStep=0;S.lessonHintArrow=line.moves[0];S.lessonSelect=null;drawLesson();refreshLessonCoach();
  }
  say(panel,'البديل جاهز على الرقعة. استخدم أزرار النقلات للمشاهدة.');
 }
 document.addEventListener('click',async e=>{
  const open=e.target.closest('[data-v7-open]');
  if(open){const panel=document.getElementById(open.dataset.v7Open==='review'?'review-ai-v7':'lesson-ai-v7');panel.hidden=false;state(panel);panel.scrollIntoView({block:'nearest',behavior:'smooth'});
   try{const status=await request('/teacher/status');provider(panel,status);say(panel,status.ready?'اسأل بطريقتك، أو ابدأ بشرح النقلة.':'المعلّم غير جاهز. راجع إعداد المزود على الخادم.',!status.ready);}catch(err){say(panel,err.message,true);}panel.querySelector('.v7-input').focus({preventScroll:true});return;}
  const b=e.target.closest('[data-v7-explain],[data-v7-ask],[data-v7-scenario],[data-v7-close]');if(!b)return;
  const panel=b.closest('.v7-tutor');if(!panel)return;
  if(b.hasAttribute('data-v7-close')){panel.hidden=true;return;}
  if(b.hasAttribute('data-v7-scenario'))playLine(panel,b.closest('.chat-message'),Number(b.dataset.v7Scenario));
  else action(panel,b.hasAttribute('data-v7-ask')?'chat':'explain');
 });
 document.addEventListener('keydown',e=>{if(e.target.matches('.v7-input')&&e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();action(e.target.closest('.v7-tutor'),'chat');}});
 // Clear stale discussion immediately when a different board position is selected.
 const lesson=document.getElementById('lesson-info');
 if(lesson)new MutationObserver(()=>{const panel=document.getElementById('lesson-ai-v7');if(panel&&!panel.hidden)state(panel);}).observe(lesson,{childList:true,subtree:true,characterData:true});
 const review=document.getElementById('move-indicator');
 if(review)new MutationObserver(()=>{const panel=document.getElementById('review-ai-v7');if(panel&&!panel.hidden)state(panel);}).observe(review,{childList:true,subtree:true,characterData:true});
})();
