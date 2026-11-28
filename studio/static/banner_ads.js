/* Manual inventory only: no auto refresh of Google units, no ad click handlers
   on Google creatives, and no request for a side unit on a narrow viewport. */
'use strict';
(()=>{
 const $=id=>document.getElementById(id),text=(ar,en)=>window.I18n?.lang==='en'?en:ar,pick=(c,key)=>c[key+'_'+(window.I18n?.lang==='en'?'en':'ar')]||'';
 const positions=['screen_top','screen_bottom','screen_left','screen_right'],views=new Set(['home','games','knowledge','learning','play','grades','course']);
 const content=document.querySelector('main.content');if(!content)return;
 const frame=document.createElement('div');frame.className='banner-layout';content.before(frame);
 const slots=new Map(),entries=new Map(),dismissed=new Set(),usedGoogle=new Set();let preview=false,cfg=null,owner=null,view='',visit='',seq=0,controller=null,poll=null,resizing=null,suppressed=true,registeredVisit=false,googlePromise=null,googleClient=null,googleBooted=false,reloading=false,session=crypto.randomUUID();
 const diagnostic={state:'idle',requests:0,google_requests:0,last_error:null};window.StudioAdvertising={status:()=>({...diagnostic,active:entries.size,preview,google_script_loaded:googleBooted})};
 const call=(path,opt={})=>{const options={...opt,signal:opt.signal||(typeof AbortSignal.timeout==='function'?AbortSignal.timeout(10000):undefined)};return typeof rawRequest==='function'?rawRequest(path,options):request(path,options);};
 for(const position of positions){const slot=document.createElement('aside');slot.id='banner-'+position;slot.className='banner-slot banner-'+position;slot.hidden=true;slot.dataset.bannerPosition=position;slots.set(position,slot);}
 frame.append(slots.get('screen_left'),content,slots.get('screen_right'));content.prepend(slots.get('screen_top'));content.append(slots.get('screen_bottom'));
 const previewBar=document.createElement('div');previewBar.className='banner-preview-bar';previewBar.hidden=true;previewBar.innerHTML='<span></span><button type="button"></button>';content.prepend(previewBar);previewBar.querySelector('button').addEventListener('click',()=>{preview=false;previewBar.hidden=true;view='';clear();changed();switchView('admin');});
 const hide=(node,value)=>{if(node.hidden!==value)node.hidden=value;};
 function blocked(){return !S.me||S.me.role==='admin'&&!preview||$('workspace').hidden||!views.has(S.view)||document.hidden||!!document.querySelector('dialog[open]')||S.view==='play'&&!$('groq-play-game')?.hidden;}
 function context(){return {view:S.view,width:Math.round(innerWidth),visit};}
 function eligible(c){return c.enabled&&c.visible!==false&&c.ends_at*1000>Date.now()&&!dismissed.has(c.id)&&(!c.placement.includes('left')&&!c.placement.includes('right')||innerWidth>=Math.max(1800,cfg?.side_min_width||1800));}
 function layout(){const left=!suppressed&&!slots.get('screen_left').hidden,right=!suppressed&&!slots.get('screen_right').hidden;frame.classList.toggle('has-left-banner',left);frame.classList.toggle('has-right-banner',right);}
 function remove(position){const entry=entries.get(position);if(entry){clearTimeout(entry.timer);clearTimeout(entry.expiry);clearTimeout(entry.fillTimer);entry.observer?.disconnect();entry.fillObserver?.disconnect();entries.delete(position);}const slot=slots.get(position);slot.replaceChildren();hide(slot,true);layout();}
 function clear(){for(const position of positions)remove(position);}
 function visibility(){if(document.hidden){for(const entry of entries.values())clearTimeout(entry.timer);return;}const next=blocked();if(next===suppressed)return;suppressed=next;frame.classList.toggle('banners-suppressed',suppressed);for(const [position,entry] of entries){clearTimeout(entry.timer);if(suppressed){hide(slots.get(position),true);if(entry.c.kind==='adsense')remove(position);}else if(eligible(entry.c)){hide(slots.get(position),false);arm(entry);}}layout();}
 function arm(entry){clearTimeout(entry.timer);if(preview||entry.delivery||entry.measuring||!entry.ready||!entry.inView||blocked()||!eligible(entry.c)||entries.get(entry.c.placement)!==entry)return;
  entry.timer=setTimeout(async()=>{if(blocked()||!entry.inView||entries.get(entry.c.placement)!==entry)return;const uid=owner,activeVisit=visit;entry.measuring=true;try{const result=await call('/promotions/banners/'+entry.c.id+'/impression',{method:'POST',body:context()});if(uid!==owner||activeVisit!==visit||entries.get(entry.c.placement)!==entry)return;if(result.show){entry.delivery=result.delivery_id;entry.element.dataset.measured='true';}else remove(entry.c.placement);}catch{/* An unacknowledged impression is not counted locally. */}finally{entry.measuring=false;}},1000);
 }
 async function google(){if(googlePromise)return cfg.google_client===googleClient?googlePromise:false;const nonce=document.querySelector('meta[name=studio-ad-nonce]')?.content;if(!nonce||!cfg?.google_ready||location.protocol!=='https:')return false;
  googleClient=cfg.google_client;googlePromise=new Promise(resolve=>{const timeout=setTimeout(()=>resolve(false),12000);const finish=value=>{clearTimeout(timeout);resolve(value);};const script=document.createElement('script');script.async=true;script.crossOrigin='anonymous';script.nonce=nonce;script.src='https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client='+encodeURIComponent(cfg.google_client);script.addEventListener('load',()=>{googleBooted=true;diagnostic.state='script-loaded';finish(true);},{once:true});script.addEventListener('error',()=>{diagnostic.last_error='google-script-unavailable';finish(false);},{once:true});document.head.append(script);});return googlePromise;
 }
 function observe(entry){if(typeof IntersectionObserver!=='function')return;entry.observer=new IntersectionObserver(changes=>{for(const change of changes){entry.inView=change.isIntersecting&&change.intersectionRatio>=.5;if(!preview&&entry.c.kind==='adsense'&&change.isIntersecting&&!entry.googleStarted&&!blocked())startGoogle(entry);arm(entry);}},{threshold:[0,.01,.5,1]});entry.observer.observe(entry.element);}
 async function startGoogle(entry){
  const position=entry.c.placement;if(entry.googleStarted||usedGoogle.has(position))return;
  const width=Math.floor(entry.element.clientWidth-2);if(width<120||blocked())return;
  entry.googleStarted=true;usedGoogle.add(position);const uid=owner;diagnostic.state='loading-google';
  const loaded=await google();if(uid!==owner||entries.get(position)!==entry)return;if(document.hidden){entry.googleStarted=false;usedGoogle.delete(position);return;}if(blocked())return;
  if(!loaded){diagnostic.state='custom-fallback';fallback(entry);return;}
  const ins=entry.ins;ins.style.display='block';
  if(position==='screen_left'||position==='screen_right'){ins.style.width='160px';ins.style.height='600px';}
  else{ins.style.width='100%';ins.style.minHeight='90px';}
  entry.element.querySelector('.banner-google-space')?.remove();entry.element.append(ins);
  try{diagnostic.google_requests++;(window.adsbygoogle=window.adsbygoogle||[]).push({});}
  catch{diagnostic.last_error='google-push-failed';fallback(entry);return;}
  const check=()=>{
   if(entries.get(position)!==entry)return;
   if(ins.dataset.adStatus==='filled'){clearTimeout(entry.fillTimer);entry.ready=true;diagnostic.state='filled';arm(entry);}
   else if(ins.dataset.adStatus==='unfilled'){diagnostic.state='unfilled';fallback(entry);}
  };
  entry.fillObserver=new MutationObserver(check);entry.fillObserver.observe(ins,{attributes:true,attributeFilter:['data-ad-status']});check();
  entry.fillTimer=setTimeout(()=>{if(!entry.ready&&entries.get(position)===entry){diagnostic.last_error='google-fill-pending';diagnostic.state='pending';}},12000);
 }
 function fallback(entry){if(entries.get(entry.c.placement)!==entry)return;const rest=entry.alternatives.filter(c=>c.id!==entry.c.id);remove(entry.c.placement);render(entry.c.placement,rest);}
 function render(position,candidates){if(blocked()||!cfg?.enabled)return;const c=candidates.find(c=>eligible(c)&&(c.kind!=='adsense'||preview||cfg.google_ready&&location.protocol==='https:'&&document.querySelector('meta[name=studio-ad-nonce]')&&!usedGoogle.has(position)));if(!c){remove(position);return;}
  const previous=entries.get(position);if(previous?.c.id===c.id&&previous.c.version===c.version)return;remove(position);
  const slot=slots.get(position),article=document.createElement('article');article.className='banner-creative banner-fit-'+(c.image_fit==='cover'?'cover':'contain');article.dataset.campaign=c.id;article.dataset.adKind=c.kind||'custom';
  const header=document.createElement('header'),label=document.createElement('span');label.className='banner-label';label.textContent=preview?text('معاينة · إعلان','Preview · Advertisement'):text('إعلان','Advertisement');header.append(label);
  const entry={c,element:article,ready:c.kind!=='adsense'&&!c.image_path,inView:false,delivery:null,alternatives:candidates,googleStarted:false};entries.set(position,entry);
  if(c.kind!=='adsense'&&c.dismissible!==false){const close=document.createElement('button');close.type='button';close.className='banner-dismiss';close.textContent='×';close.setAttribute('aria-label',text('إخفاء هذا الإعلان','Dismiss this advertisement'));close.addEventListener('click',()=>{dismissed.add(c.id);remove(position);if(!preview)call('/promotions/banners/'+c.id+'/dismiss',{method:'POST',body:{}}).catch(()=>{});});header.append(close);}article.append(header);
  if(c.kind==='adsense'&&preview){const placeholder=document.createElement('div');placeholder.className='banner-google-preview';placeholder.textContent=text('موضع Google — لا تحميل أثناء المعاينة','Google placement — not loaded in preview');article.append(placeholder);}
  else if(c.kind==='adsense'){const ins=document.createElement('ins');ins.className='adsbygoogle banner-google';ins.dataset.adClient=cfg.google_client;ins.dataset.adSlot=c.adsense_slot;ins.dataset.adFormat=position==='screen_left'||position==='screen_right'?'vertical':'horizontal';ins.dataset.fullWidthResponsive='false';entry.ins=ins;const space=document.createElement('div');space.className='banner-google-space';article.append(space);}
  else{
   if(c.image_path){const image=document.createElement('img');image.src=c.image_path;image.alt=pick(c,'alt')||pick(c,'title');image.loading='lazy';image.decoding='async';image.className='banner-poster';image.addEventListener('load',()=>{entry.ready=true;arm(entry);},{once:true});image.addEventListener('error',()=>fallback(entry),{once:true});
    if(c.link_url){const link=document.createElement('a');link.href=c.link_url;link.target='_blank';link.rel='sponsored noopener noreferrer';link.dataset.bannerLink=c.id;link.append(image);article.append(link);}else article.append(image);
   }
   const copy=document.createElement('div');copy.className='banner-copy';const title=document.createElement('h3');title.className='banner-title';title.textContent=pick(c,'title');copy.append(title);
   if(pick(c,'body')){const body=document.createElement('p');body.className='banner-description';body.textContent=pick(c,'body');copy.append(body);}
   if(c.link_url){const link=document.createElement('a');link.href=c.link_url;link.target='_blank';link.rel='sponsored noopener noreferrer';link.dataset.bannerLink=c.id;link.className='banner-cta';link.textContent=pick(c,'button')||text('اعرف المزيد','Learn more');copy.append(link);}article.append(copy);
  }
  slot.append(article);hide(slot,false);layout();entry.expiry=setTimeout(()=>remove(position),Math.min(2147483000,Math.max(1,c.ends_at*1000-Date.now())));observe(entry);
 }
 function apply(data){const wasEnabled=cfg?.enabled;cfg=data.config;if(wasEnabled===false&&cfg?.enabled)document.dispatchEvent(new Event('advertising:enabled'));if(!cfg?.enabled){clear();document.dispatchEvent(new Event('advertising:disabled'));return;}const grouped=new Map(positions.map(p=>[p,[]]));for(const campaign of data.items||[])if(grouped.has(campaign.placement))grouped.get(campaign.placement).push(campaign);
  const selected=[...grouped].filter(([,items])=>items.some(eligible)).sort((a,b)=>(b[1][0]?.priority||0)-(a[1][0]?.priority||0)).slice(0,cfg.max_active||4).map(([p])=>p);
  for(const position of positions){const current=entries.get(position),items=grouped.get(position);if(!selected.includes(position)){remove(position);continue;}const kept=current&&items.find(c=>c.id===current.c.id&&eligible(c));if(kept&&kept.version===current.c.version&&(kept.kind!=='adsense'||preview||cfg.google_ready&&current.ins?.dataset.adClient===cfg.google_client)){current.c=kept;current.alternatives=items;continue;}render(position,items);}
 }
 async function refresh(first=false){first=first||(!registeredVisit&&cfg?.enabled!==false);visibility();if(blocked())return;const uid=S.me.id,activeView=S.view,token=++seq;controller?.abort();controller=new AbortController();const activeController=controller,timeout=setTimeout(()=>activeController.abort(),8000);try{const ctx=context();diagnostic.requests++;const data=await call(preview?'/control/advertising/preview?'+new URLSearchParams({view:ctx.view,width:ctx.width}):first?'/promotions/banners/select':'/promotions/banners?'+new URLSearchParams(ctx),{method:!preview&&first?'POST':'GET',...(!preview&&first?{body:ctx}:{}),signal:controller.signal});if(uid!==S.me?.id||activeView!==S.view||token!==seq)return;registeredVisit=data.visit_registered!==false;if(!preview&&data.config.google_ready&&(data.items||[]).some(c=>c.kind==='adsense')&&!document.querySelector('meta[name=studio-ad-nonce]'))bootstrap(data.config);apply(data);if(!first&&cfg.enabled&&!registeredVisit)refresh(true);}catch(err){if(err.name!=='AbortError'&&uid===owner&&activeView===S.view&&token===seq){diagnostic.last_error='inventory-unavailable';clear();}}finally{clearTimeout(timeout);}}
 function bootstrap(config){
  if(reloading||location.protocol!=='https:')return;if(S.view!=='home'||document.activeElement?.matches('input,textarea,[contenteditable=true]')){diagnostic.last_error='reload-required-for-google';return;}
  const key='studio-ad-bootstrap:'+S.me.id+':'+config.google_client;
  try{const last=Number(sessionStorage.getItem(key)||0);if(Date.now()-last<60000){diagnostic.last_error='nonce-missing-after-reload';return;}sessionStorage.setItem(key,String(Date.now()));}
  catch{diagnostic.last_error='bootstrap-storage-unavailable';return;}
  reloading=true;diagnostic.state='reloading-for-csp';location.reload();
 }
 function schedule(){clearTimeout(poll);if(!S.me||S.me.role==='admin'&&!preview||document.hidden||!views.has(S.view))return;poll=setTimeout(async()=>{await refresh();schedule();},15000);}
 function changed(){const uid=S.me?.id;if(uid!==owner){owner=uid;seq++;controller?.abort();clear();dismissed.clear();view='';session=crypto.randomUUID();}visibility();if(!uid||S.me.role==='admin'&&!preview||!views.has(S.view)) {clear();schedule();return;}if(view!==S.view){view=S.view;visit=session+':'+crypto.randomUUID();registeredVisit=false;seq++;controller?.abort();clear();refresh(true);}else if(!blocked()&&!entries.size)refresh();schedule();}
 document.addEventListener('advertising:preview',()=>{if(S.me?.role!=='admin')return;preview=true;previewBar.hidden=false;previewBar.querySelector('span').textContent=text('معاينة إدارية — لا تُحتسب مشاهدات ولا تُحمّل إعلانات Google.','Admin preview — no impressions or Google requests.');previewBar.querySelector('button').textContent=text('إنهاء المعاينة','Exit preview');view='';changed();});
 document.addEventListener('studio:view',changed);document.addEventListener('studio:session',event=>{if(googleBooted&&(event.detail?.id!==owner||S.me?.role==='admin')){location.reload();return;}owner=null;preview=false;previewBar.hidden=true;seq++;controller?.abort();clear();clearTimeout(poll);view='';});
 document.addEventListener('visibilitychange',()=>{visibility();if(!document.hidden){changed();for(const entry of entries.values()){arm(entry);if(entry.c.kind==='adsense'&&entry.inView&&!entry.googleStarted&&!blocked())startGoogle(entry);}}else clearTimeout(poll);});
 window.addEventListener('resize',()=>{visibility();for(const [position,entry] of entries)if(!eligible(entry.c))remove(position);clearTimeout(resizing);resizing=setTimeout(()=>{refresh();schedule();},250);});
 for(const dialog of document.querySelectorAll('dialog'))new MutationObserver(()=>{visibility();if(!blocked())changed();}).observe(dialog,{attributes:true,attributeFilter:['open']});
 new MutationObserver(changed).observe($('workspace'),{attributes:true,attributeFilter:['hidden']});
 const training=$('groq-play-game');if(training)new MutationObserver(()=>{visibility();if(!blocked())changed();}).observe(training,{attributes:true,attributeFilter:['hidden']});
 document.addEventListener('click',event=>{const link=event.target.closest('[data-banner-link]');if(!link)return;const entry=[...entries.values()].find(x=>x.c.id===link.dataset.bannerLink);if(entry?.delivery)call('/promotions/'+entry.delivery+'/click',{method:'POST',body:{}}).catch(()=>{});});
 window.addEventListener('pagehide',()=>{seq++;controller?.abort();clearTimeout(poll);clearTimeout(resizing);clear();});
 window.addEventListener('pageshow',event=>{if(event.persisted){view='';changed();}});
 document.addEventListener('languagechange',()=>{previewBar.querySelector('span').textContent=text('معاينة إدارية — لا تُحتسب مشاهدات ولا تُحمّل إعلانات Google.','Admin preview — no impressions or Google requests.');previewBar.querySelector('button').textContent=text('إنهاء المعاينة','Exit preview');for(const entry of entries.values()){entry.element.querySelector('.banner-label').textContent=preview?text('معاينة · إعلان','Preview · Advertisement'):text('إعلان','Advertisement');entry.element.querySelector('.banner-dismiss')?.setAttribute('aria-label',text('إخفاء هذا الإعلان','Dismiss this advertisement'));const title=entry.element.querySelector('.banner-title'),description=entry.element.querySelector('.banner-description'),link=entry.element.querySelector('.banner-cta'),image=entry.element.querySelector('img');if(title)title.textContent=pick(entry.c,'title');if(description)description.textContent=pick(entry.c,'body');if(link)link.textContent=pick(entry.c,'button')||text('اعرف المزيد','Learn more');if(image)image.alt=pick(entry.c,'alt')||pick(entry.c,'title');}});
 changed();
})();
