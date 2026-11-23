'use strict';
(()=>{
 const $=id=>document.getElementById(id),side=document.querySelector('.sidebar'),mq=matchMedia('(max-width:780px)'),en=()=>window.I18n?.lang==='en',text=(ar,eng)=>en()?eng:ar;
 if(!side)return;
 const overlay=document.createElement('button');overlay.id='drawer-backdrop';overlay.className='drawer-backdrop';overlay.type='button';overlay.hidden=true;overlay.tabIndex=-1;
 const closer=document.createElement('button');closer.id='drawer-close';closer.className='drawer-close';closer.type='button';closer.textContent='×';side.prepend(closer);$('workspace').append(overlay);
 const nav=document.createElement('nav');nav.id='mobile-nav';nav.className='mobile-nav';nav.dataset.noI18n='';$('workspace').append(nav);
 side.id='studio-sidebar';$('menu').setAttribute('aria-controls',side.id);
 const routes=[['home','⌂','الرئيسية','Home'],['learning','▤','مساري','My path'],['play','♞','العب','Play'],['knowledge','♜','تعلّم','Learn'],['games','♟','مبارياتي','Games']];
 function labels(){nav.setAttribute('aria-label',text('التنقل الرئيسي','Main navigation'));nav.innerHTML=routes.map(([v,i,ar,eng])=>`<button type="button" data-view="${v}"><span aria-hidden="true">${i}</span><span>${en()?eng:ar}</span></button>`).join('');overlay.setAttribute('aria-label',text('إغلاق القائمة','Close menu'));closer.setAttribute('aria-label',text('إغلاق القائمة','Close menu'));sync();}
 function sync(){const opened=mq.matches&&side.classList.contains('open');overlay.hidden=!opened;side.inert=mq.matches&&!opened;document.querySelector('.main-wrapper').inert=opened;nav.inert=opened;$('menu').setAttribute('aria-expanded',String(opened));document.documentElement.classList.toggle('drawer-open',opened);const active=document.querySelector('#nav button.active')?.dataset.view;nav.querySelectorAll('button').forEach(b=>{if(b.dataset.view===active)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});}
 function close(){side.classList.remove('open');sync();$('menu').focus();}
 overlay.addEventListener('click',close);closer.addEventListener('click',close);
 $('menu').addEventListener('click',()=>{sync();if(mq.matches&&side.classList.contains('open'))closer.focus();});
 side.addEventListener('keydown',e=>{if(!mq.matches||!side.classList.contains('open'))return;if(e.key==='Escape'){e.preventDefault();close();}if(e.key==='Tab'){const controls=[...side.querySelectorAll('button,summary,a[href]')].filter(x=>!x.hidden&&x.getClientRects().length&&!x.closest('details:not([open])')||x.tagName==='SUMMARY');const first=controls[0],last=controls.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}}});
 new MutationObserver(sync).observe(side,{attributes:true,attributeFilter:['class'],subtree:true});mq.addEventListener('change',()=>{side.classList.remove('open');sync();});document.addEventListener('languagechange',labels);labels();
})();
