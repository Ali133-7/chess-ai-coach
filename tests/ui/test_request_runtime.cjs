const fs=require('node:fs'),assert=require('node:assert/strict'),{JSDOM}=require('jsdom');
const dom=new JSDOM('',{runScripts:'outside-only'}),w=dom.window;w.structuredClone=structuredClone;w.eval(fs.readFileSync('studio/static/request_runtime.js','utf8'));
(async()=>{
 let calls=0,release;const send=()=>{calls++;return new Promise(r=>release=r);};
 const a=w.StudioRequests.get('alice:ar','/games',send),b=w.StudioRequests.get('alice:ar','/games',send);await Promise.resolve();assert.equal(calls,1);release({items:[1]});const x=await a,y=await b;x.items.push(2);assert.equal(y.items.length,1);
 await w.StudioRequests.get('bob:ar','/games',async()=>{calls++;return {};});assert.equal(calls,2);
 await assert.rejects(w.StudioRequests.get('alice:ar','/fail',async()=>{throw Error('offline');}));await w.StudioRequests.get('alice:ar','/fail',async()=>({ok:true}));assert.equal(w.StudioRequests.metrics().in_flight,0);
 let firstSignal;w.request=(path,opt)=>{if(path==='/one'){firstSignal=opt.signal;return new Promise((_,reject)=>opt.signal.addEventListener('abort',()=>reject(Error('aborted'))));}return Promise.resolve({});};
 const one=w.StudioRequests.latest('review','/one').catch(()=>{});await w.StudioRequests.latest('review','/two');await one;assert(firstSignal.aborted);
 console.log('REQUEST_RUNTIME_OK: coalescing, account scope, independent response clones, error cleanup and latest-request cancellation.');w.close();
})().catch(e=>{console.error(e);w.close();process.exitCode=1;});
