/* Searchable, keyboard-operated selects. The original select remains the form
   value and validation source; searching alone never changes that value. */
'use strict';
(()=>{
 const entries=new WeakMap();let active=null,serial=0;
 const text=(ar,en)=>window.I18n?.lang==='en'?en:ar;
 const normal=value=>String(value).normalize('NFKD').replace(/[\u0300-\u036f\u064b-\u065f]/g,'').toLocaleLowerCase().trim();
 function enhance(root=document){for(const select of root.querySelectorAll('select:not(.language-select):not([multiple])')){
  if(!entries.has(select))build(select);sync(select);
 }}
 function build(select){
  const wrap=document.createElement('div');wrap.className='admin-select';select.before(wrap);wrap.append(select);select.classList.add('admin-select-native');select.tabIndex=-1;select.setAttribute('aria-hidden','true');
  const input=document.createElement('input');input.type='text';input.className='admin-select-input';input.autocomplete='off';input.spellcheck=false;input.setAttribute('role','combobox');input.setAttribute('aria-autocomplete','list');input.setAttribute('aria-haspopup','listbox');input.setAttribute('aria-expanded','false');
  const toggle=document.createElement('button');toggle.type='button';toggle.className='admin-select-toggle';toggle.tabIndex=-1;toggle.innerHTML='<span aria-hidden="true">⌄</span>';
  const menu=document.createElement('div');menu.className='admin-select-menu';menu.hidden=true;
  const list=document.createElement('div');list.className='admin-select-options';list.id='admin-options-'+(++serial);list.setAttribute('role','listbox');input.setAttribute('aria-controls',list.id);menu.append(list);wrap.append(input,toggle,menu);
  const item={select,wrap,input,toggle,menu,list,open:false,query:'',index:-1,visible:[],signature:''};entries.set(select,item);
  input.addEventListener('click',()=>open(item));
  input.addEventListener('input',()=>{item.query=input.value;if(!item.open)open(item,true);render(item);});
  toggle.addEventListener('click',()=>{if(item.open)close(item);else{open(item);input.focus();}});
  input.addEventListener('focus',()=>input.select());
  input.addEventListener('blur',()=>setTimeout(()=>{if(!wrap.contains(document.activeElement))close(item);},0));
  input.addEventListener('keydown',event=>{
   if(['ArrowDown','ArrowUp'].includes(event.key)){event.preventDefault();if(!item.open){open(item);return;}highlight(item,item.index+(event.key==='ArrowDown'?1:-1));}
   else if(item.open&&['Home','End'].includes(event.key)){event.preventDefault();highlight(item,event.key==='Home'?0:item.visible.length-1);}
   else if(item.open&&event.key==='Enter'){event.preventDefault();if(item.visible[item.index])choose(item,item.visible[item.index]);}
   else if(item.open&&event.key==='Escape'){event.preventDefault();event.stopPropagation();close(item);}
   else if(event.key==='Tab')close(item);
  });
  list.addEventListener('mousedown',event=>event.preventDefault());
  list.addEventListener('click',event=>{const option=event.target.closest('[data-select-index]');if(option)choose(item,select.options[Number(option.dataset.selectIndex)]);});
  select.addEventListener('change',()=>sync(select));
  select.addEventListener('invalid',event=>{event.preventDefault();input.setAttribute('aria-invalid','true');input.focus();open(item);});
 }
 function sync(select){const item=entries.get(select);if(!item)return;
  const label=select.getAttribute('aria-label')||select.closest('label')?.querySelector('span')?.textContent||select.name||text('اختر قيمة','Choose an option');
  item.input.setAttribute('aria-label',label);item.list.setAttribute('aria-label',label);item.toggle.setAttribute('aria-label',text('عرض الخيارات','Show options'));
  item.input.placeholder=text('ابحث أو اختر…','Search or choose…');item.input.disabled=select.disabled;item.toggle.disabled=select.disabled;item.input.setAttribute('aria-required',String(select.required));
  if(!item.open)item.input.value=select.selectedOptions[0]?.textContent||'';
  else render(item);
 }
 function open(item,keepQuery=false){if(item.select.disabled)return;if(active&&active!==item)close(active);active=item;if(item.open)return;
  item.open=true;if(!keepQuery)item.query='';item.menu.hidden=false;item.input.setAttribute('aria-expanded','true');item.wrap.classList.add('is-open');render(item);
  const rect=item.input.getBoundingClientRect(),dialog=item.wrap.closest('dialog'),bounds=dialog?.getBoundingClientRect();
  const bottom=Math.min(innerHeight,bounds?.bottom||innerHeight)-16,top=Math.max(0,bounds?.top||0)+60,height=Math.min(240,innerHeight*.32,item.menu.scrollHeight||240);
  item.wrap.classList.toggle('opens-up',bottom-rect.bottom<height&&rect.top-top>bottom-rect.bottom);
 }
 function close(item){if(!item)return;item.open=false;item.query='';item.menu.hidden=true;item.input.value=item.select.selectedOptions[0]?.textContent||'';item.input.setAttribute('aria-expanded','false');item.input.removeAttribute('aria-activedescendant');item.wrap.classList.remove('is-open','opens-up');if(active===item)active=null;}
 function render(item){
  const options=[...item.select.options];item.visible=options.filter(option=>!option.hidden&&!option.disabled&&!option.parentElement.disabled&&normal(option.textContent).includes(normal(item.query)));
  item.list.replaceChildren();
  for(const option of item.visible){const button=document.createElement('button');button.type='button';button.tabIndex=-1;button.setAttribute('role','option');button.setAttribute('aria-selected',String(option.selected));button.dataset.selectIndex=options.indexOf(option);button.id=item.list.id+'-'+options.indexOf(option);button.textContent=option.textContent;item.list.append(button);}
  if(!item.visible.length){const empty=document.createElement('p');empty.className='admin-select-empty';empty.setAttribute('role','status');empty.textContent=text('لا توجد خيارات مطابقة','No matching options');item.list.append(empty);}
  highlight(item,Math.max(0,item.visible.indexOf(item.select.selectedOptions[0])));
 }
 function highlight(item,index){item.index=item.visible.length?Math.max(0,Math.min(index,item.visible.length-1)):-1;for(const [at,node] of [...item.list.querySelectorAll('[role=option]')].entries()){node.classList.toggle('is-highlighted',at===item.index);if(at===item.index){item.input.setAttribute('aria-activedescendant',node.id);if(node.offsetTop<item.list.scrollTop)item.list.scrollTop=node.offsetTop;else if(node.offsetTop+node.offsetHeight>item.list.scrollTop+item.list.clientHeight)item.list.scrollTop=node.offsetTop+node.offsetHeight-item.list.clientHeight;}}if(item.index<0)item.input.removeAttribute('aria-activedescendant');}
 function choose(item,option){if(!option||option.disabled||option.parentElement.disabled)return;const changed=item.select.value!==option.value;item.select.value=option.value;item.input.removeAttribute('aria-invalid');close(item);item.input.focus();if(changed)item.select.dispatchEvent(new Event('change',{bubbles:true}));}
 document.addEventListener('pointerdown',event=>{if(active&&!active.wrap.contains(event.target))close(active);});
 window.addEventListener('resize',()=>close(active));
 window.AdminSelect={enhance,sync,close:()=>close(active)};
})();
