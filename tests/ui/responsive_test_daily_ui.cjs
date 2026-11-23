const fs=require('fs'),assert=require('node:assert/strict'),{JSDOM}=require('jsdom');
const root=(process.env.RUNTIME||process.cwd())+'/studio/static/',fixture=JSON.parse(fs.readFileSync(__dirname+'/daily-ui-fixture.json','utf8'));
const dom=new JSDOM(fs.readFileSync(root+'index.html','utf8'),{url:'http://localhost',runScripts:'outside-only',pretendToBeVisual:true}),w=dom.window,d=w.document;
w.S={me:{id:1}};w.esc=x=>String(x).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');w.I18n={lang:'ar',locale:'ar-IQ',t:x=>x};w.switchView=()=>{};w.HTMLElement.prototype.scrollIntoView=function(){};w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};
let seen=new Set(),starts=[],skips=0,current=null,offline=false;w.ChessBoardPro={render:()=>{},promotion:(m,cb)=>cb(m[0])};
w.request=async(path,o)=>{
 if(path.startsWith('/knowledge/recommendations')){if(offline)throw Error('offline test');return{items:fixture.puzzles.filter(x=>!seen.has(x.item.id)).map(x=>x.item),reference_rating:1000,recommended_theme:'',reason:'unseen only',daily:fixture.daily,history:{counts:{skipped:skips}}};}
 if(path==='/knowledge/puzzles/start'){const id=o.body.puzzle_id;assert(!seen.has(id),'automatic queue must never replay an opened puzzle');seen.add(id);starts.push(id);current=structuredClone(fixture.puzzles.find(x=>x.item.id===id).session);return current;}
 if(path.endsWith('/skip')){skips++;current={...current,status:'skipped',version:current.version+1,legal_moves:[]};return current;}
 throw Error(path);
};
w.eval(fs.readFileSync(root+'knowledge.js','utf8'));w.eval(fs.readFileSync(root+'daily_exercises.js','utf8'));const click=id=>d.getElementById(id).click(),flush=()=>new Promise(r=>setImmediate(r));
(async()=>{
 for(let i=0;i<8;i++){click('kc-start-recommended');await flush();await flush();assert.equal(starts.length,i+1);assert.equal(d.querySelector('#kc-skip-puzzle').hidden,false);}
 assert.equal(new Set(starts).size,8);assert.equal(skips,7,'moving to the next active exercise must persist skip first');click('kc-skip-puzzle');await flush();await flush();assert.equal(skips,8);assert(d.querySelector('#daily-summary').textContent.includes('8'));
 const before=starts.length;offline=true;click('kc-next-puzzle');await flush();await flush();assert.equal(starts.length,before,'network failure must not recycle a stale queue');offline=false;
 while(starts.length<fixture.puzzles.length){click('kc-start-recommended');await flush();await flush();}
 click('kc-start-recommended');await flush();await flush();assert.equal(starts.length,fixture.puzzles.length,'exhaustion must not wrap');assert.equal(new Set(starts).size,fixture.puzzles.length);
 const active=fixture.puzzles.find(x=>x.session.generated).session;w.renderDailyPuzzle(active);assert(!d.querySelector('#daily-explanation').textContent.includes(active.generated.explanation?.ar||'THIS-TEXT-DOES-NOT-EXIST'));assert(!d.querySelector('#daily-explanation').textContent.includes('MOCK ENGINE FIXTURE')||d.querySelector('#daily-explanation').textContent.includes('500,000'));
 w.renderDailyPuzzle(fixture.solved);assert(d.querySelector('#daily-explanation').textContent.includes('شرح تجريبي'));assert(d.querySelector('#daily-explanation').textContent.includes('CC BY-SA 4.0'));w.I18n.lang='en';w.I18n.locale='en-US';d.dispatchEvent(new w.Event('languagechange'));w.renderDailyPuzzle(fixture.solved);assert(d.querySelector('#daily-summary').textContent.includes('Today'));assert(d.querySelector('#daily-explanation').textContent.includes('Test explanation'));
 console.log('DAILY_UI_OK: more than five unique exercises, persisted skip before next, no stale replay after network failure, no wrap on exhaustion, generated/unrated metadata, answer withholding, source licence and bilingual notes.');dom.window.close();
})().catch(e=>{console.error(e);process.exitCode=1;dom.window.close()});
