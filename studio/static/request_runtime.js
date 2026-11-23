'use strict';
(()=>{
 const pending=new Map(),latest=new Map();let epoch=0,requests=0,coalesced=0,longTasks=0;
 window.StudioRequests={
  get(scope,path,send){const key=epoch+':'+scope+':'+path;if(pending.has(key)){coalesced++;return pending.get(key).then(structuredClone);}requests++;const promise=Promise.resolve().then(send);pending.set(key,promise);promise.finally(()=>{if(pending.get(key)===promise)pending.delete(key);}).catch(()=>{});return promise.then(structuredClone);},
  invalidate(){epoch++;pending.clear();},
  latest(key,path,opt={}){latest.get(key)?.abort();const c=new AbortController();latest.set(key,c);return request(path,{...opt,signal:c.signal}).finally(()=>{if(latest.get(key)===c)latest.delete(key);});},
  cancel(key){latest.get(key)?.abort();latest.delete(key);},
  metrics(){return {coalescible_gets_sent:requests,coalesced_gets:coalesced,in_flight:pending.size,long_tasks:longTasks,scope:'Only GETs eligible for coalescing; explicit abortable reads are excluded.'};}
 };
 try{new PerformanceObserver(list=>{longTasks+=list.getEntries().length;}).observe({type:'longtask',buffered:true});}catch{}
})();
