/* Unified move-quality labels for completed games and private practice. */
'use strict';
(function(){
 const ITEMS={
  brilliant:{label:'مدهشة',symbol:'!!'},excellent:{label:'ممتازة',symbol:'!'},
  good:{label:'جيدة',symbol:'✓'},weak:{label:'ضعيفة',symbol:'?!'},
  missed:{label:'ضياع فرصة',symbol:'○'},mistake:{label:'خطأ',symbol:'?'},
  blunder:{label:'خطأ فادح',symbol:'??'}
 };
 const LEGACY={best:'excellent',inaccuracy:'weak','الأفضل':'excellent','عدم دقة':'weak',
   'غير دقيقة':'weak','ممتازة':'excellent','جيدة':'good','ضعيفة':'weak',
   'هفوة كبيرة':'blunder','خطأ':'mistake','خطأ فادح':'blunder','ضياع فرصة':'missed'};
 const normalize=code=>ITEMS[code]?code:(LEGACY[code]||null);
 const html=code=>{const key=normalize(code),x=ITEMS[key];return x?'<span class="grade-mini grade-'+key+'" title="'+x.label+'" aria-label="'+x.label+'">'+x.symbol+'</span>':'';};
 const detail=code=>ITEMS[normalize(code)]||null;
 window.MoveGrade={items:ITEMS,normalize,html,detail};
})();
