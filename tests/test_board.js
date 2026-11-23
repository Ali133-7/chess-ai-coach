'use strict';
/* No network: verify 64 board squares, correct orientation, quality markers,
   hint arrow, legal pointer drag, and transition-safe rendering. */
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict'),path=require('node:path');
class Element{
 constructor(tag){this.tag=tag;this.children=[];this.dataset={};this.style={};this.listeners={};this.attrs={};this.classList={add:()=>{},remove:()=>{},toggle:()=>{}};this.className='';}
 append(...items){this.children.push(...items);}
 appendChild(item){this.children.push(item);}
 replaceChildren(...items){this.children=[];for(const item of items)this.children.push(...(item.tag==='fragment'?item.children:[item]));}
 setAttribute(k,v){this.attrs[k]=v;}
 addEventListener(type,cb){(this.listeners[type]??=[]).push(cb);}
 closest(selector){return selector==='[data-square]'&&this.dataset.square?this:null;}
 contains(other){return this.children.includes(other);}
 querySelector(selector){return null;}
 querySelectorAll(selector){return selector==='[data-square]'?this.children.filter(x=>x.dataset.square):[];}
 getBoundingClientRect(){return {width:640,height:640};}
 remove(){}
}
const document={listeners:{},body:new Element('body'),createElement:tag=>new Element(tag),
 createElementNS:(_ns,tag)=>new Element(tag),createDocumentFragment:()=>new Element('fragment'),
 addEventListener(type,cb){(this.listeners[type]??=[]).push(cb);},elementFromPoint:()=>null};
const window={};const context={window,document,performance:{now:()=>0},console,matchMedia:()=>({matches:true})};
const root=path.resolve(__dirname,'../web');
vm.runInNewContext(fs.readFileSync(root+'/quality-ui.js','utf8'),context);
vm.runInNewContext(fs.readFileSync(root+'/board-pro.js','utf8'),context);
const {render,parseFen,point,arrowSvg}=window.ChessBoardPro;
const fen='rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
assert.equal(Object.keys(parseFen(fen)).length,32);
assert.equal(parseFen(fen).d1,'Q');assert.equal(parseFen(fen).d8,'q');
const board=new Element('board');let moved='';
render(board,fen,'white',{legalMoves:['e2e3','e2e4'],onMove:(from,to)=>moved=from+to});
assert.equal(board.children.length,64);
assert.equal(board.children.filter(x=>x.children.some(child=>child.tag==='img')).length,32);
assert.equal(board.children.at(-1).dataset.square,'h1');
const from=board.children.find(x=>x.dataset.square==='e2');
const dest=board.children.find(x=>x.dataset.square==='e4');
document.elementFromPoint=()=>dest;
board.listeners.pointerdown[0]({button:0,target:from,pointerId:1,clientX:100,clientY:200});
document.listeners.pointermove[0]({pointerId:1,clientX:100,clientY:280});
document.listeners.pointerup[0]({pointerId:1,clientX:100,clientY:280});
assert.equal(moved,'e2e4');
window.ChessBoardPro.optimistic(board,'e2e4');
assert.equal(parseFen(board.dataset.renderedFen).e4,'P');
assert.equal(parseFen(board.dataset.renderedFen).e2,undefined);
render(board,fen,'black',{legalMoves:['e2e3'],onMove:()=>{}});
assert.equal(board.children[0].dataset.square,'h1');
const after='rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1';
render(board,after,'white',{last:['e2','e4'],lastUci:'e2e4',quality:{code:'excellent',uci:'e2e4'},hintArrow:'g8f6'});
assert.equal(board.children.filter(x=>x.tag==='button').length,64);
const target=board.children.find(x=>x.dataset.square==='e4');
assert.ok(target.children.some(x=>x.className.includes('piece-grade')&&x.textContent==='!'));
assert.ok(board.children.some(x=>x.tag==='svg'));
const gradeCodes=['brilliant','excellent','good','weak','missed','mistake','blunder'];
assert.equal(Object.keys(window.MoveGrade.items).length,7);
for(const code of gradeCodes)assert.ok(window.MoveGrade.html(code).includes('grade-'+code));
assert.equal(window.MoveGrade.normalize('هفوة كبيرة'),'blunder');
assert.equal(window.MoveGrade.normalize('best'),'excellent');
assert.equal(point('a8','white').x,6.25);
assert.equal(point('h1','black').x,6.25);
assert.ok(arrowSvg('e2e4','white'));
render(board,after,'white',{selected:'e4'});assert.equal(board.children.filter(x=>x.tag==='button').length,64);
console.log('V5 browser-board tests passed: 64 squares, drag, 7 quality marks, hint arrow, orientation.');
