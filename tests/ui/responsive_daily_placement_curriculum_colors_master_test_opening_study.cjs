const {JSDOM}=require('jsdom'),fs=require('fs'),assert=require('node:assert/strict');
const root=(process.env.RUNTIME||process.cwd())+'/studio/static/',fixture=JSON.parse(fs.readFileSync(__dirname+'/study-fixture.json','utf8'));
const d=new JSDOM(fs.readFileSync(root+'index.html','utf8'),{url:'http://localhost/',runScripts:'outside-only',pretendToBeVisual:true}),w=d.window,doc=w.document;
w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};
w.S={me:{id:1},review:null};w.esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');w.I18n={locale:'ar-IQ',t:x=>x};w.switchView=()=>{};
let timers=new Map(),serial=0,config,calls=[];w.setTimeout=(fn)=>{timers.set(++serial,fn);return serial};w.clearTimeout=id=>timers.delete(id);
w.ChessBoardPro={render:(el,fen,side,c)=>{config=c;el.dataset.testFen=fen},promotion:(ms,cb)=>cb(ms[0])};
w.request=async(path,opts)=>{calls.push(path);if(path.includes('/study'))return structuredClone(fixture);if(path.startsWith('/knowledge/openings?'))return {items:[fixture],total:1};throw Error('Unexpected network request: '+path)};
w.eval(fs.readFileSync(root+'knowledge.js','utf8'));const flush=()=>new Promise(r=>setImmediate(r));const click=id=>doc.getElementById(id).click();const ply=()=>doc.getElementById('kc-ply').textContent;const runTimer=async()=>{const [id,fn]=timers.entries().next().value;timers.delete(id);fn();await flush()};
(async()=>{
 doc.querySelector('[data-kc-family="Italian Game"]').click();await flush();assert(doc.getElementById('kc-study-dialog').open);assert.equal(doc.activeElement.id,'kc-study-close');assert.equal(doc.querySelectorAll('[data-kc-step]').length,fixture.path.length);const before=calls.length;
 click('kc-study-mode');assert.equal(timers.size,1);await runTimer();assert(ply().includes('e4'));assert(doc.getElementById('kc-note-why').textContent.length>5);await runTimer();assert(ply().includes('e5'));assert.equal(calls.length,before,'autoplay must not request each ply');click('kc-study-mode');assert.equal(timers.size,0);
 click('kc-study-mode');click('kc-next');await flush();assert.equal(timers.size,0,'manual navigation pauses');click('kc-practice-mode');await flush();assert.equal(timers.size,0);config.onMove('e2','e4');await flush();assert(ply().includes('e5'),'opponent replies from lesson');
 click('kc-study-mode');click('kc-study-close');assert.equal(timers.size,0);assert(!doc.documentElement.classList.contains('kc-study-open'));assert(!doc.getElementById('kc-study-dialog').open);
 doc.querySelector('[data-kc-family="Italian Game"]').click();await flush();w.I18n.locale='en-US';doc.dispatchEvent(new w.Event('languagechange'));click('kc-next');await flush();assert.equal(doc.getElementById('kc-note-title').textContent,'Move idea: e4');assert(!/[\u0600-\u06ff]/.test(doc.getElementById('kc-note-why').textContent));const ev=new w.Event('cancel',{cancelable:true});doc.getElementById('kc-study-dialog').dispatchEvent(ev);assert(ev.defaultPrevented);click('kc-study-close');
 doc.querySelector('[data-kc-family="Italian Game"]').click();await flush();click('kc-study-mode');for(let i=0;i<fixture.path.length+1;i++)await runTimer();assert.equal(timers.size,0);assert(ply().includes(fixture.path.at(-1).san));click('kc-study-mode');assert.equal(timers.size,1);assert.equal(ply(),'البداية');click('kc-study-close');
 console.log('OPENING_STUDY_UI_OK: autoplay, single timer, pause, manual seek, no per-ply network, practice, close cleanup, focus, bilingual facts, cancel veto.');d.window.close();
})().catch(e=>{console.error(e);process.exitCode=1;d.window.close()});

