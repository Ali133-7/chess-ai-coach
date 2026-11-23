'use strict';
(()=>{
 document.addEventListener('click',async e=>{
  const learn=e.target.closest('[data-learn]');if(learn){switchView('knowledge');await window.loadKnowledge?.();window.selectKnowledgeTab?.(learn.dataset.learn);document.querySelector('#view-knowledge')?.scrollIntoView({block:'start'});}
 });
 document.addEventListener('languagechange',()=>{if(S.me){if(S.view==='home')loadHome();if(S.view==='games')loadGames();if(S.view==='grades')loadGrades();}document.querySelectorAll('.language-select').forEach(x=>x.value=window.I18n.lang);});
})();
