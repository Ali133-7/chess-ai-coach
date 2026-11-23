const fs=require('node:fs'),assert=require('node:assert/strict'),{JSDOM}=require('jsdom');
const root=(process.env.RUNTIME||process.cwd())+'/studio/static/';
const dom=new JSDOM(fs.readFileSync(root+'index.html','utf8'),{url:'https://studio.example.net',runScripts:'outside-only',pretendToBeVisual:true}),w=dom.window,d=w.document;
w.I18n={lang:'ar'};w.S={me:{role:'user'},view:'knowledge'};w.esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};w.HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new w.Event('close'));};
const free={id:'free',title_ar:'مجاني',title_en:'Free',description_ar:'',description_en:'',price_iqd:0,days:30,features:{knowledge:true}},pro={...free,id:'pro',price_iqd:5000};
const campaign={delivery_id:'delivery',placement:'modal',title_ar:'<script>attack</script>',title_en:'Test',body_ar:'شرح',body_en:'Notes',button_ar:'اعرف المزيد',button_en:'More',link_url:'https://example.net',image_path:''};
const calls=[];w.request=async(path,opt={})=>{calls.push([path,opt]);if(path==='/site-info')return {site_name:'Studio',tagline_ar:'تعلم',tagline_en:'Learn'};if(path==='/billing/catalog')return {plans:[free,pro],features:{knowledge:['معرفة','Knowledge']},gateways:[{name:'google_play',enabled:true,ready:true}]};if(path==='/billing/me')return {plan:free};if(path==='/billing/orders')return {items:[]};if(path==='/promotions/event')return {items:[campaign]};if(path.endsWith('/display'))return {show:true,campaign};return {};};
w.switchView=()=>{};w.eval(fs.readFileSync(root+'billing_promotions.js','utf8'));
const flush=async()=>{await new Promise(r=>setImmediate(r));await new Promise(r=>setImmediate(r));};
(async()=>{
 await w.loadBilling();assert(d.querySelector('[data-buy-plan="pro"]').disabled,'Google Play must not create a fake web checkout');
 d.querySelector('#workspace').hidden=false;await flush();assert(!d.querySelector('#promotion-dialog').open,'must not interrupt knowledge study');
 w.S.view='home';d.querySelector('#view-knowledge').hidden=true;await flush();assert(d.querySelector('#promotion-dialog').open);
 assert(!d.querySelector('#promotion-dialog-content script'));assert(d.querySelector('#promotion-dialog-content').textContent.includes('<script>attack</script>'));
 d.querySelector('#promotion-dialog-close').click();assert(!d.querySelector('#promotion-dialog').open);
 assert(calls.some(([p])=>p==='/promotions/delivery/display'));console.log('BILLING_PROMOTIONS_OK: no fake Google web checkout, study deferral, confirmed display, escaped copy, X close.');dom.window.close();
})().catch(e=>{console.error(e);process.exitCode=1;dom.window.close();});
