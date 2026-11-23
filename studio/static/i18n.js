'use strict';
(()=>{
 const catalog=window.STUDIO_TRANSLATIONS||{},records=new WeakMap(),attributes=new WeakMap(),cache=new Map();
 const clean=s=>s.replace(/\s+/g,' ').trim(),arabic=/[\u0600-\u06ff]/,digit=s=>s.replace(/[٠-٩]/g,c=>String(c.charCodeAt(0)-1632)).replace(/٬/g,',').replace(/٫/g,'.');
 let lang='ar';try{if(localStorage.getItem('chess-studio-language')==='en')lang='en';}catch{}
 let patterns,fragments;
 function prepare(){if(patterns)return;const entries=Object.entries(catalog);patterns=entries.filter(([s])=>/__V\d+__/.test(s)&&(s.replace(/__V\d+__/g,'').match(/[\u0621-\u064a]/g)||[]).length>=8).sort((a,b)=>b[0].length-a[0].length).map(([source,target])=>({parts:source.split(/__V\d+__/),ids:source.match(/__V\d+__/g),target})).filter(p=>p.parts.slice(1,-1).every(Boolean));fragments=entries.filter(([s])=>!/__V\d+__/.test(s)&&arabic.test(s)&&s.length>=3).sort((a,b)=>b[0].length-a[0].length);}
 function match(key,p){const parts=p.parts;if(!key.startsWith(parts[0])||!key.endsWith(parts.at(-1)))return null;let pos=parts[0].length,values=[];for(let i=0;i<p.ids.length;i++){const literal=parts[i+1],end=i===p.ids.length-1?key.length-literal.length:key.indexOf(literal,pos);if(end<pos)return null;values.push(key.slice(pos,end));pos=end+literal.length;}return pos===key.length?values:null;}
 function text(value,depth=0){const original=String(value??'');if(lang!=='en'||!arabic.test(original))return lang==='en'?digit(original):original;if(cache.has(original))return cache.get(original);const key=clean(original),leading=original.match(/^\s*/)[0],trailing=original.match(/\s*$/)[0];let result=catalog[key];
  if(result===undefined){const label=key.match(/^(.+?) (\([0-9,]+\))$/);if(label&&catalog[label[1]])result=catalog[label[1]]+' '+label[2];}
  if(result===undefined){prepare();if(depth<8){for(const p of patterns){const values=match(key,p);if(!values)continue;result=p.target;for(let i=0;i<p.ids.length;i++)result=result.split(p.ids[i]).join(text(values[i],depth+1));break;}}}
  if(result===undefined){prepare();result=key;for(const [from,to] of fragments)if(result.includes(from))result=result.split(from).join(to);}
  const output=leading+digit(result)+trailing;if(cache.size>=2048)cache.delete(cache.keys().next().value);cache.set(original,output);return output;
 }
 const ignored=el=>el?.closest('script,style,textarea,input,code,pre,[data-no-i18n],.chat-user,.v7-user');
 function translateNode(node){if(ignored(node.parentElement)||!node.nodeValue?.trim())return;const old=records.get(node),source=old&&node.nodeValue===old.rendered?old.source:node.nodeValue,rendered=text(source);records.set(node,{source,rendered});if(node.nodeValue!==rendered)node.nodeValue=rendered;}
 const attrNames=['title','placeholder','aria-label','alt'],attrSelector='[title],[placeholder],[aria-label],[alt]';
 function translateAttributes(el){if(el.closest('[data-no-i18n]'))return;let map=attributes.get(el);if(!map){map={};attributes.set(el,map);}for(const name of attrNames){if(!el.hasAttribute(name))continue;const current=el.getAttribute(name),old=map[name],source=old&&current===old.rendered?old.source:current,rendered=text(source);map[name]={source,rendered};if(current!==rendered)el.setAttribute(name,rendered);}}
 function translateRoot(root){if(!root.isConnected)return;if(root.nodeType===Node.TEXT_NODE){translateNode(root);return;}if(root.nodeType!==Node.ELEMENT_NODE||ignored(root))return;translateAttributes(root);const walk=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);let node;while(node=walk.nextNode())translateNode(node);for(const el of root.querySelectorAll(attrSelector))translateAttributes(el);}
 const pending=new Set(),pendingAttributes=new Set();let scheduled=null,observer;
 const frame=cb=>window.requestAnimationFrame?window.requestAnimationFrame(cb):window.setTimeout(cb,0);
 const cancel=id=>window.cancelAnimationFrame?window.cancelAnimationFrame(id):window.clearTimeout(id);
 function observe(){if(lang==='en'&&document.body)observer.observe(document.body,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:attrNames});}
 function collect(changes){for(const change of changes){if(change.type==='attributes')pendingAttributes.add(change.target);else if(change.type==='characterData')pending.add(change.target);else for(const node of change.addedNodes)if(node.nodeType===Node.ELEMENT_NODE||node.nodeType===Node.TEXT_NODE)pending.add(node);}}
 function flush(){scheduled=null;collect(observer.takeRecords());observer.disconnect();const roots=[...pending].filter(n=>n.isConnected);pending.clear();const attrs=[...pendingAttributes];pendingAttributes.clear();for(const root of roots){let parent=root.parentNode,covered=false;while(parent){if(roots.includes(parent)){covered=true;break;}parent=parent.parentNode;}if(!covered)translateRoot(root);}for(const el of attrs)if(el.isConnected)translateAttributes(el);observe();}
 function schedule(changes){if(lang!=='en')return;collect(changes);if(scheduled===null&&(pending.size||pendingAttributes.size))scheduled=frame(flush);}
 function apply(){if(!document.body)return;observer?.disconnect();if(scheduled!==null){cancel(scheduled);scheduled=null;}pending.clear();pendingAttributes.clear();translateRoot(document.body);document.querySelectorAll('.language-select').forEach(s=>s.value=lang);document.documentElement.lang=lang;document.documentElement.dir=lang==='ar'?'rtl':'ltr';const title=lang==='ar'?'Chess Studio — تعلّم الشطرنج':'Chess Studio — Learn chess';if(document.title!==title)document.title=title;observe();}
 function set(value){if(!['ar','en'].includes(value)||value===lang)return;lang=value;try{localStorage.setItem('chess-studio-language',lang);}catch{}apply();document.dispatchEvent(new CustomEvent('languagechange',{detail:{language:lang}}));}
 window.I18n={get lang(){return lang;},get locale(){return lang==='en'?'en-US':'ar-IQ';},t:text,apply,set};
 document.documentElement.lang=lang;document.documentElement.dir=lang==='ar'?'rtl':'ltr';
 const nativeConfirm=window.confirm.bind(window),nativePrompt=window.prompt.bind(window);window.confirm=message=>nativeConfirm(text(message));window.prompt=(message,value)=>nativePrompt(text(message),value);
 document.addEventListener('change',e=>{if(e.target.matches('.language-select'))set(e.target.value);});
 observer=new MutationObserver(schedule);apply();
})();
