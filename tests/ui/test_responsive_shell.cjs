const fs=require('fs'),assert=require('node:assert/strict'),{JSDOM}=require('jsdom');
const root=(process.env.RUNTIME||process.cwd())+'/studio/static/';
const dom=new JSDOM(fs.readFileSync(root+'index.html','utf8'),{url:'http://localhost',runScripts:'outside-only',pretendToBeVisual:true}),w=dom.window,d=w.document;
let mobile=true,onChange;w.matchMedia=()=>({get matches(){return mobile},addEventListener:(_,fn)=>onChange=fn});w.I18n={lang:'ar'};
const side=d.querySelector('.sidebar');d.querySelector('#menu').addEventListener('click',()=>side.classList.toggle('open'));
d.addEventListener('click',e=>{const b=e.target.closest('button[data-view]');if(b){d.querySelectorAll('#nav button').forEach(x=>x.classList.toggle('active',x.dataset.view===b.dataset.view));side.classList.remove('open');}});
w.eval(fs.readFileSync(root+'responsive_studio.js','utf8'));const flush=()=>new Promise(r=>setImmediate(r));
(async()=>{
 assert(side.inert,'closed mobile drawer must be inaccessible');assert(d.querySelector('#drawer-backdrop').hidden);assert.equal(d.querySelectorAll('#mobile-nav button').length,5);
 d.querySelector('#menu').click();assert.equal(d.querySelector('#menu').getAttribute('aria-expanded'),'true');assert(!side.inert);assert(d.querySelector('.main-wrapper').inert,'background is inaccessible while drawer is open');assert.equal(d.activeElement.id,'drawer-close');
 d.querySelector('#drawer-close').click();assert(side.inert);assert(!d.querySelector('.main-wrapper').inert);assert.equal(d.activeElement.id,'menu');assert(d.querySelector('#drawer-backdrop').hidden);
 d.querySelector('#menu').click();d.querySelector('#drawer-backdrop').click();assert(!side.classList.contains('open'));
 d.querySelector('#menu').click();side.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));assert(!side.classList.contains('open'));
 d.querySelector('#mobile-nav [data-view="learning"]').click();await flush();assert.equal(d.querySelector('#mobile-nav [aria-current="page"]').dataset.view,'learning');
 w.I18n.lang='en';d.dispatchEvent(new w.Event('languagechange'));assert(d.querySelector('#mobile-nav').textContent.includes('My path'));assert(!/[\u0600-\u06ff]/.test(d.querySelector('#mobile-nav').textContent));
 mobile=false;onChange();assert(!side.inert);assert(d.querySelector('#drawer-backdrop').hidden);assert(!d.documentElement.classList.contains('drawer-open'));mobile=true;onChange();assert(side.inert);
 assert(d.querySelector('#view-home .getting-started [data-view="learning"]'));assert.equal(d.querySelectorAll('.view-guide').length,5);
 await flush();console.log('RESPONSIVE_SHELL_OK: 5 routes, drawer close/escape/backdrop, focus and background inertness, active route, locale, viewport change, beginner entry and contextual help.');dom.window.close();
})().catch(e=>{console.error(e);process.exitCode=1;dom.window.close()});
