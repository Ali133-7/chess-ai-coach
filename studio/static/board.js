/* V4 premium interactive chessboard: 64 accessible squares, marker badges,
   arrows, pointer drag, click-to-move, animated piece transitions and promotion. */
'use strict';
(function(){
 const FILES='abcdefgh';
 const names={K:'ملك أبيض',Q:'وزير أبيض',R:'قلعة بيضاء',B:'فيل أبيض',N:'حصان أبيض',P:'بيدق أبيض',k:'ملك أسود',q:'وزير أسود',r:'قلعة سوداء',b:'فيل أسود',n:'حصان أسود',p:'بيدق أسود'};
 const asset={K:'wK',Q:'wQ',R:'wR',B:'wB',N:'wN',P:'wP',k:'bK',q:'bQ',r:'bR',b:'bB',n:'bN',p:'bP'};
 const configs=new WeakMap(),animations=new WeakMap();
 function parseFen(fen){
  const out={};const ranks=String(fen||'').split(' ')[0].split('/');if(ranks.length!==8)return out;
  ranks.forEach((rank,row)=>{let i=0;for(const ch of rank){if(/[1-8]/.test(ch))i+=Number(ch);else if(i<8){out[FILES[i]+(8-row)]=ch;i++;}}});return out;
 }
 function point(square,orientation){
  if(!/^[a-h][1-8]$/.test(square||''))return null;
  const file=FILES.indexOf(square[0]),rank=Number(square[1]);
  return orientation==='white'?{x:(file+.5)*12.5,y:(8.5-rank)*12.5}:{x:(7.5-file)*12.5,y:(rank-.5)*12.5};
 }
 function arrowSvg(uci,orientation){
  if(!/^[a-h][1-8][a-h][1-8][qrbn]?$/.test(uci||''))return null;
  const a=point(uci.slice(0,2),orientation),b=point(uci.slice(2,4),orientation);
  if(!a||!b)return null;
  const dx=b.x-a.x,dy=b.y-a.y,l=Math.hypot(dx,dy)||1,ux=dx/l,uy=dy/l;
  const ex=b.x-ux*5.5,ey=b.y-uy*5.5;
  const poly=[[ex+uy*2.2,ey-ux*2.2],[b.x,b.y],[ex-uy*2.2,ey+ux*2.2]].map(x=>x.join(',')).join(' ');
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
  svg.setAttribute('class','board-hint-overlay');svg.setAttribute('viewBox','0 0 100 100');svg.setAttribute('aria-hidden','true');
  const line=document.createElementNS(svg.namespaceURI,'line');
  for(const [k,v] of Object.entries({x1:a.x,y1:a.y,x2:ex-ux*1.5,y2:ey-uy*1.5,stroke:'#12d4a3','stroke-width':2.1,'stroke-linecap':'round',opacity:.92}))line.setAttribute(k,v);
  svg.append(line);
  const head=document.createElementNS(svg.namespaceURI,'polygon');head.setAttribute('points',poly);head.setAttribute('fill','#12d4a3');head.setAttribute('opacity','.93');svg.append(head);
  return svg;
 }
 function render(el,fen,orientation='white',options={}){
  if(!el)return;
  const prev=animations.get(el)||{},pieces=parseFen(fen);
  const files=orientation==='white'?[...FILES]:[...FILES].reverse();
  const ranks=orientation==='white'?[8,7,6,5,4,3,2,1]:[1,2,3,4,5,6,7,8];
  const targets=new Set(options.targets||[]),last=new Set(options.last||[]);
  const valid=options.legalMoves||[];
  // Selection and hint updates do not rebuild the 64 DOM nodes or reload images.
  if(el.dataset.renderedFen===fen && el.dataset.orientation===orientation && el.querySelectorAll('[data-square]').length===64){
   for(const btn of el.querySelectorAll('[data-square]')){
    const sq=btn.dataset.square;
    btn.classList.toggle('selected',options.selected===sq);
    btn.classList.toggle('target',targets.has(sq));
    btn.classList.toggle('last',last.has(sq));
    btn.querySelector('.piece-grade')?.remove();
    const code=window.MoveGrade?.normalize(options.quality?.code||options.quality?.quality_code);
    const detail=window.MoveGrade?.detail(code);
    if(detail&&sq===options.quality?.uci?.slice(2,4)){
     const badge=document.createElement('span');badge.className='piece-grade grade-'+code;
     badge.textContent=detail.symbol;badge.title=detail.label;btn.append(badge);
    }
   }
   el.querySelector('.board-hint-overlay')?.remove();
   const arrow=arrowSvg(options.hintArrow,orientation);if(arrow)el.append(arrow);
   configs.set(el,{options,pieces,legalMoves:valid});
   return;
  }
  const frag=document.createDocumentFragment();
  const gradeCode=window.MoveGrade?.normalize(options.quality?.code||options.quality?.quality_code);
  const gradedSquare=options.quality?.uci?.slice(2,4);
  const grade=window.MoveGrade?.detail(gradeCode);
  for(let r=0;r<8;r++)for(let c=0;c<8;c++){
   const file=files[c],rank=ranks[r],sq=file+rank,piece=pieces[sq];
   const button=document.createElement('button');button.type='button';button.dataset.square=sq;
   button.className='square '+(((FILES.indexOf(file)+rank)%2===0)?'light':'dark')+
    (options.selected===sq?' selected':'')+(targets.has(sq)?' target':'')+(last.has(sq)?' last':'')+(piece?' occupied':'');
   button.setAttribute('aria-label',sq+(piece?' '+names[piece]:' فارغ')+(grade&&sq===gradedSquare?' · نقلة '+grade.label:''));
   button.setAttribute('role','gridcell');
   if(piece){const img=document.createElement('img');img.className='piece piece-3d';img.alt='';img.draggable=false;img.src='/assets/pieces/'+asset[piece]+'.png';button.append(img);}
   if(grade&&sq===gradedSquare){const mark=document.createElement('span');mark.className='piece-grade grade-'+gradeCode;mark.title='جودة النقلة: '+grade.label;mark.setAttribute('aria-label',grade.label);mark.textContent=grade.symbol;button.append(mark);}
   if(c===0){const sp=document.createElement('span');sp.className='coord rank';sp.textContent=rank;button.append(sp);}
   if(r===7){const sp=document.createElement('span');sp.className='coord file';sp.textContent=file;button.append(sp);}
   frag.append(button);
  }
  const uci=options.hintArrow;
  const arrow=arrowSvg(uci,orientation);if(arrow)frag.append(arrow);
  el.replaceChildren(frag);el.dataset.orientation=orientation;el.dataset.renderedFen=fen;
  configs.set(el,{options,pieces,legalMoves:valid});
  const lastUci=options.lastUci||null;
  if(prev.fen!==fen&&lastUci&&lastUci!==prev.lastUci&&prev.orientation===orientation&&prev.fen){
   const before=parseFen(prev.fen),from=lastUci.slice(0,2),to=lastUci.slice(2,4);
   if(before[from]&&pieces[to]){
    const node=el.querySelector('[data-square="'+to+'"] .piece-3d');
    const start=point(from,orientation),end=point(to,orientation);
    if(node&&start&&end&&typeof node.animate==='function'&&!matchMedia('(prefers-reduced-motion: reduce)').matches){
     const size=el.getBoundingClientRect().width;
     node.animate([{transform:'translate('+((start.x-end.x)*size/100)+'px,'+((start.y-end.y)*size/100)+'px) scale(1.07)',opacity:.95},{transform:'translate(0,0) scale(1)',opacity:1}],{duration:240,easing:'cubic-bezier(.19,.82,.2,1)'});
    }
   }
  }
  animations.set(el,{fen,orientation,lastUci});
  if(!el.dataset.dragSetup){el.dataset.dragSetup='1';addInteractions(el);}
 }
 function addInteractions(el){
  let dragging=null,ignoreUntil=0,frame=0;
  el.addEventListener('click',e=>{
   if(performance.now()<ignoreUntil)return;
   const sq=e.target.closest('[data-square]')?.dataset.square;
   if(sq)configs.get(el)?.options.onClick?.(sq);
  });
  el.addEventListener('pointerdown',e=>{
   const sq=e.target.closest('[data-square]')?.dataset.square,cfg=configs.get(el);
   if(e.button!==0||!sq||!cfg?.options.onMove||!cfg.legalMoves.some(m=>m.startsWith(sq)))return;
   dragging={id:e.pointerId,from:sq,startX:e.clientX,startY:e.clientY,moved:false,ghost:null};
  });
  document.addEventListener('pointermove',e=>{
   if(!dragging||e.pointerId!==dragging.id)return;
   if(!dragging.moved&&Math.hypot(e.clientX-dragging.startX,e.clientY-dragging.startY)<5)return;
   if(!dragging.moved){
    dragging.moved=true;document.body.classList.add('piece-dragging');
    const p=configs.get(el)?.pieces[dragging.from];
    if(p){const ghost=document.createElement('img');ghost.alt='';ghost.className='piece-ghost';ghost.src='/assets/pieces/'+asset[p]+'.png';
      ghost.style.width=ghost.style.height=Math.min(96,el.getBoundingClientRect().width/8*1.04)+'px';(document.querySelector('dialog[open]')||document.body).append(ghost);dragging.ghost=ghost;}
    el.querySelector('[data-square="'+dragging.from+'"] .piece-3d')?.classList.add('drag-source');
   }
   if(dragging.ghost){
    dragging.x=e.clientX;dragging.y=e.clientY;
    if(!frame)frame=(typeof requestAnimationFrame==='function'?requestAnimationFrame:(cb=>{cb();return 1}))(()=>{frame=0;if(dragging?.ghost){dragging.ghost.style.transform='translate3d('+dragging.x+'px,'+dragging.y+'px,0) translate(-50%,-65%)';}});
   }
  },{passive:true});
  document.addEventListener('pointerup',e=>{
   if(!dragging||dragging.id!==e.pointerId)return;
   const {from,moved}=dragging;
   dragging.ghost?.remove();dragging=null;document.body.classList.remove('piece-dragging');
   el.querySelector('.drag-source')?.classList.remove('drag-source');
   if(!moved)return;
   ignoreUntil=performance.now()+340;
   const target=document.elementFromPoint(e.clientX,e.clientY)?.closest('[data-square]');
   const to=target&&el.contains(target)?target.dataset.square:null;
   const cfg=configs.get(el);
   if(to&&cfg?.legalMoves.some(m=>m.startsWith(from+to)))cfg.options.onMove?.(from,to);
   else cfg?.options.onInvalid?.();
  });
  document.addEventListener('pointercancel',()=>{dragging?.ghost?.remove();dragging=null;el.querySelector('.drag-source')?.classList.remove('drag-source');document.body.classList.remove('piece-dragging');});
 }
 function promotion(moves,callback){
  if(!moves?.length)return;
  if(moves.length===1){callback(moves[0]);return;}
  document.getElementById('promotion-chooser')?.remove();
  const overlay=document.createElement('div');overlay.id='promotion-chooser';overlay.className='promotion-backdrop';
  overlay.innerHTML='<div class="promotion-panel" role="dialog" aria-modal="true"><h3>اختر قطعة الترقية</h3><div class="promotion-options"></div><button class="btn btn-outline close-promotion" type="button">إلغاء</button></div>';
  const row=overlay.querySelector('.promotion-options');
  for(const move of moves){const p=move.slice(-1),b=document.createElement('button');b.type='button';b.className='promotion-item';b.setAttribute('aria-label',p);
   const img=document.createElement('img');img.alt=p.toUpperCase();img.src='/assets/pieces/'+(Number(move[1])===7?'w':'b')+p.toUpperCase()+'.png';b.append(img);
   b.addEventListener('click',()=>{overlay.remove();callback(move);});row.append(b);
  }
  overlay.querySelector('.close-promotion').addEventListener('click',()=>overlay.remove());
  overlay.addEventListener('click',e=>{if(e.target===overlay)overlay.remove();});
  (document.querySelector('dialog[open]')||document.body).append(overlay);overlay.querySelector('.promotion-item')?.focus();
 }
 function optimistic(el,uci){
  const cfg=configs.get(el),fen=el.dataset.renderedFen;
  if(!cfg||!fen||!/^[a-h][1-8][a-h][1-8][qrbn]?$/.test(uci))return;
  const b={...parseFen(fen)},from=uci.slice(0,2),to=uci.slice(2,4),p=b[from];
  if(!p)return;
  const diag=from[0]!==to[0];
  if(p.toLowerCase()==='p'&&diag&&!b[to])delete b[to[0]+from[1]];
  delete b[from];
  if(p.toLowerCase()==='k'&&Math.abs('abcdefgh'.indexOf(to[0])-'abcdefgh'.indexOf(from[0]))===2){
   const short=to[0]==='g',a=(short?'h':'a')+from[1],z=(short?'f':'d')+from[1];
   if(b[a]){b[z]=b[a];delete b[a];}
  }
  b[to]=uci.length===5?(p===p.toUpperCase()?uci[4].toUpperCase():uci[4]):p;
  const ranks=[];
  for(let r=8;r>=1;r--){let row='',empties=0;for(const f of FILES){const pc=b[f+r];if(pc){if(empties){row+=empties;empties=0;}row+=pc;}else empties++;}if(empties)row+=empties;ranks.push(row);}
  const parts=fen.split(' ');parts[0]=ranks.join('/');parts[1]=parts[1]==='w'?'b':'w';
  render(el,parts.join(' '),el.dataset.orientation,{...cfg.options,selected:null,targets:[],legalMoves:[],hintArrow:null,
    last:[from,to],lastUci:uci,quality:null});
 }
 window.ChessBoardPro={render,parseFen,promotion,point,arrowSvg,optimistic};
})();
