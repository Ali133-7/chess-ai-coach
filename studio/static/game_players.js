/* Shared player identities for recorded games. Colours come from PGN sides,
   never from names, the result, board orientation or the signed-in account. */
'use strict';
(()=>{
 const rails=new WeakMap(),english=()=>window.I18n?.lang==='en',text=(ar,en)=>english()?en:ar;
 const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const colour=side=>text(side==='white'?'الأبيض':'الأسود',side==='white'?'White':'Black');
 const same=(a,b)=>!!String(a||'').trim()&&String(a).trim().toLowerCase()===String(b||'').trim().toLowerCase();
 function sideFor(game,username){return same(game.white,username)?'white':same(game.black,username)?'black':null;}
 function score(result,side){return result==='1/2-1/2'?'½':result==='1-0'?(side==='white'?'1':'0'):result==='0-1'?(side==='black'?'1':'0'):'';}
 function row(game,side,username){
  const value=score(game.result,side),title=String(game[side+'_title']||'').trim();
  return `<div class="match-player" data-side="${side}" data-no-i18n><span class="match-piece" aria-hidden="true">♟</span><div class="match-identity"><div class="match-name-line">${title?`<span class="match-title" dir="ltr">${escape(title)}</span>`:''}<bdi class="match-name" dir="auto">${escape(game[side]||text('لاعب غير مسمّى','Unnamed player'))}</bdi><span class="match-you" ${same(game[side],username)?'':'hidden'}>${text('أنت','You')}</span></div><div class="match-labels"><span class="match-color">${colour(side)}</span><span class="match-turn" hidden>${text('صاحب الدور','To move')}</span></div></div>${value?`<span class="match-score" dir="ltr" aria-label="${text('النتيجة المسجلة','Recorded score')}: ${value}">${value}</span>`:''}</div>`;
 }
 function card(game,username){return `<div class="match-pair">${row(game,'white',username)}${row(game,'black',username)}</div>`;}
 function board(board,game,{orientation='white',fen='',username='',finished=false}={}){
  let state=rails.get(board);
  if(!game){if(state)for(const node of state.nodes)node.hidden=true;board.removeAttribute('data-has-players');return;}
  const key=JSON.stringify([game.white,game.black,game.white_title,game.black_title,game.result,username]);
  if(!state||state.key!==key){
   if(state)for(const node of state.nodes)node.remove();
   const nodes=['white','black'].map(side=>{const box=document.createElement('div');box.innerHTML=row(game,side,username);const node=box.firstElementChild;node.classList.add('match-player-rail');node.dataset.matchBoard=board.id;return node;});
   state={key,nodes};rails.set(board,state);
  }
  const bottom=state.nodes[orientation==='black'?1:0],top=state.nodes[orientation==='black'?0:1];
  if(board.previousElementSibling!==top)board.before(top);
  if(board.nextElementSibling!==bottom)board.after(bottom);
  board.dataset.hasPlayers='true';
  const turn=finished?null:({w:'white',b:'black'}[fen.split(' ')[1]]||null);
  for(const node of state.nodes){node.hidden=false;const active=node.dataset.side===turn;node.classList.toggle('match-to-move',active);node.querySelector('.match-turn').hidden=!active;}
 }
 function labels(){for(const node of document.querySelectorAll('.match-player')){
  node.querySelector('.match-color').textContent=colour(node.dataset.side);
  node.querySelector('.match-you').textContent=text('أنت','You');
  node.querySelector('.match-turn').textContent=text('صاحب الدور','To move');
  const value=node.querySelector('.match-score');if(value)value.setAttribute('aria-label',text('النتيجة المسجلة','Recorded score')+': '+value.textContent);
 }}
 document.addEventListener('languagechange',labels);
 window.GamePlayers={card,board,sideFor,score};
})();
