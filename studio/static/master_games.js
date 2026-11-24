'use strict';
(()=>{
 let offset=0,sequence=0,loaded=false,busy=false;
 const el=id=>document.getElementById(id),en=()=>window.I18n?.lang==='en',say=(ar,eng)=>en()?eng:ar;
 async function load(append=false){
  if(busy)return;busy=true;const seq=++sequence;el('master-more').disabled=true;
  try{
   if(!append){offset=0;el('master-games').replaceChildren();}
   const params=new URLSearchParams({q:el('master-query').value.trim(),limit:'12',offset:String(offset)});
   params.set('scope',el('master-scope')?.value||'gm');
   if(el('master-year').value)params.set('year',el('master-year').value);
   if(el('master-result').value)params.set('result',el('master-result').value);
   const r=await request('/knowledge/masters?'+params);if(seq!==sequence)return;
   if(!loaded){el('master-year').insertAdjacentHTML('beforeend',r.years.map(y=>`<option value="${y}">${y}</option>`).join(''));loaded=true;}
   el('master-count').textContent=say(r.total+' مباراة مطابقة من '+r.all_count+' مباراة فعلية.',r.total+' matches from '+r.all_count+' real games.')+(r.expanded_library?say(' · أرشيف محلي موسّع. البحث ببداية كلمات الاسم أو الافتتاحية.',' · Expanded local archive. Search by player or opening word prefixes.'):'');
   el('master-games').insertAdjacentHTML('beforeend',r.items.map(g=>`<article class="master-game"><p class="tiny muted" data-no-i18n>${esc(g.date)} · ${esc(g.eco)} · ${esc(g.result)}</p><h3 data-no-i18n><bdi>${esc(g.white)}</bdi> <span>×</span> <bdi>${esc(g.black)}</bdi></h3><p data-no-i18n>${esc(g.event)}</p><p class="tiny muted" data-no-i18n>${esc(g.opening)}</p><button class="primary" data-master-game="${g.id}">${esc(say('شاهد وتعلّم','Watch and learn'))}</button></article>`).join(''));
   offset+=r.items.length;el('master-more').hidden=offset>=r.total;
   if(!r.total)el('master-games').textContent=say('لا توجد مباريات بهذه المرشحات. جرّب اسماً أو سنة أخرى.','No games match these filters. Try another name or year.');
  }catch(e){el('master-count').textContent=e.message;}finally{busy=false;el('master-more').disabled=false;}
 }
 window.loadMasterLibrary=()=>{if(!loaded)load();};
 el('master-search-form').addEventListener('submit',e=>{e.preventDefault();load();});
 el('master-more').addEventListener('click',()=>load(true));
 document.addEventListener('click',e=>{const b=e.target.closest('[data-master-game]');if(b)window.openMasterStudy(b.dataset.masterGame);});
 document.addEventListener('languagechange',()=>{if(loaded&&document.querySelector('[data-kc-tab="masters"]').getAttribute('aria-selected')==='true')load();});
})();
