'use strict';
(()=>{
 let loaded=false,busy=false,offset=0,query='',side='all',queued=false;
 const el=id=>document.getElementById(id),en=()=>window.I18n?.lang==='en',txt=(ar,eng)=>en()?eng:ar;
 async function load(append=false){
  if(busy){if(!append)queued=true;return;}busy=true;el('trap-more').disabled=true;
  try{
   if(!append){offset=0;query=el('trap-query').value.trim();side=el('trap-side').value;el('trap-cards').replaceChildren();}
   const r=await request('/knowledge/traps?'+new URLSearchParams({q:query,side,limit:'12',offset:String(offset)}));loaded=true;
   el('trap-count').textContent=txt(r.total+' دراسة مطابقة من '+r.all_count+'؛ تشمل مداخل الفهرس المسماة Trap وعددها '+r.catalogue_entries+'.',r.total+' matching studies of '+r.all_count+', covering all '+r.catalogue_entries+' Trap-named catalogue entries.');
   el('trap-cards').insertAdjacentHTML('beforeend',r.items.map(p=>`<article class="trap-card"><span class="trap-owner ${p.side}">${p.side==='white'?'○':'●'} ${esc(txt(p.side==='white'?'يلعب الفكرة الأبيض':'يلعب الفكرة الأسود',p.side==='white'?'Idea played by White':'Idea played by Black'))}</span><h3 data-no-i18n>${esc(en()?p.name:p.name_ar)}</h3><p data-no-i18n>${esc(p.idea[en()?'en':'ar'])}</p><small data-no-i18n>${esc(txt('التهيئة: ','Setup: ')+p.timing.setup_ply)}</small><button class="primary" data-trap-open="${esc(p.id)}">${esc(txt('افهم الفخ وجرّبه','Study and practice'))}</button></article>`).join(''));
   offset+=r.items.length;el('trap-more').hidden=offset>=r.total;
   if(!r.total)el('trap-cards').textContent=txt('لا توجد دراسات بهذه المرشحات.','No studies match these filters.');
  }catch(e){el('trap-count').textContent=e.message;}finally{busy=false;el('trap-more').disabled=false;if(queued){queued=false;load();}}
 }
 window.loadTrapLibrary=()=>{if(!loaded)load();};
 el('trap-search-form').addEventListener('submit',e=>{e.preventDefault();load();});el('trap-more').addEventListener('click',()=>load(true));
 document.addEventListener('click',e=>{const b=e.target.closest('[data-trap-open]');if(b)window.openTrapStudy(b.dataset.trapOpen);});
 document.addEventListener('languagechange',()=>{if(loaded&&document.querySelector('[data-kc-tab="traps"]').getAttribute('aria-selected')==='true')load();});
})();
