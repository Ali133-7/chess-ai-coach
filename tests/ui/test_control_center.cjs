const fs=require('node:fs'),assert=require('node:assert/strict'),{JSDOM}=require('jsdom');
const root=(process.env.RUNTIME||process.cwd())+'/studio/static/';
const dom=new JSDOM(fs.readFileSync(root+'index.html','utf8'),{url:'https://studio.example.net',runScripts:'outside-only'}),w=dom.window,d=w.document;
const errors=[];w.addEventListener('error',e=>errors.push(e.error));
w.S={me:{role:'admin'}};w.I18n={lang:'ar',locale:'ar-IQ'};w.esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};w.HTMLDialogElement.prototype.close=function(){this.open=false;};
const plan={id:'free',title_ar:'مجاني',title_en:'Free',description_ar:'',description_en:'',price_iqd:0,days:30,enabled:true,features:{knowledge:true},limits:{teacher_daily:20},version:1};
const responses={plans:{items:[plan]},overview:{stats:{users:2},jobs:[],daily:{},features:{knowledge:['المعرفة','Knowledge']}},users:{items:[],total:0,page:1,limit:25},discounts:{items:[]},gateways:{items:['zaincash','fib','google_play'].map(name=>({name,enabled:false,environment:'sandbox',ready:false,public:{},configured_secrets:{}}))},campaigns:{items:[]},orders:{items:[],google_play:[],total:0,page:1},audit:{items:[],total:0},providers:{enabled:true,primary:'groq',fallback:[],models:{groq:'test-model'},configured:{groq:true}},settings:{site_name:'Studio',tagline_ar:'تعلم',tagline_en:'Learn',support_email:'',ai_enabled:true,daily_enabled:true,daily_target:24,maintenance:false,maintenance_ar:'صيانة',maintenance_en:'Maintenance'}};
const calls=[];w.request=async(path,options)=>{calls.push([path,options]);return structuredClone(responses[path.split('/')[2].split('?')[0]]||{});};
w.loadLegacyAdmin=async()=>{};w.eval(fs.readFileSync(root+'control_center.js','utf8'));
const flush=async()=>{await new Promise(r=>setImmediate(r));await new Promise(r=>setImmediate(r));};
(async()=>{
 await w.loadControl();assert.equal(d.querySelectorAll('[data-control-tab]').length,11);
 for(const tab of ['users','plans','discounts','providers','gateways','campaigns','orders','settings','engine','audit','overview']){
  d.querySelector(`[data-control-tab="${tab}"]`).click();await flush();assert.equal(errors.length,0,tab);
 }
 d.querySelector('[data-control-tab="gateways"]').click();await flush();d.querySelector('[data-control-edit="gateway"][data-id="google_play"]').click();await flush();
 assert(d.querySelector('#control-dialog').open);assert(d.querySelector('[name="service_account_file"]'));assert(!d.querySelector('[name="service_account_file"]').value);
 d.querySelector('#control-dialog-close').click();assert(!d.querySelector('#control-dialog').open);
 d.querySelector('[data-control-tab="providers"]').click();await flush();
 const secret=d.querySelector('[name="key_groq"]');assert(secret);assert.equal(secret.type,'password');assert.equal(secret.value,'');secret.value='typed-but-never-from-server';
 w.I18n.lang='en';d.dispatchEvent(new w.Event('languagechange'));assert.equal(secret.value,'typed-but-never-from-server');assert(d.querySelector('#control-nav').textContent.includes('AI providers'));
 d.querySelector('[data-control-tab="plans"]').click();await flush();d.querySelector('[data-control-new="plan"]').click();await flush();
 assert(d.querySelector('[data-control-form="plan"]'));assert.equal(errors.length,0);assert(!d.querySelector('#control-dialog').textContent.includes('<script>'));
 console.log('CONTROL_CENTER_OK: 11 sections, provider password fields, Google Android settings, dialog close, language switch preserves edits.');dom.window.close();
})().catch(e=>{console.error(e);dom.window.close();process.exitCode=1;});

