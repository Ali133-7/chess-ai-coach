'use strict';
(()=>{
 const dialog=document.getElementById('review-modal'),review=document.getElementById('review');let returnFocus=null;
 if(!dialog||!review)return;
 dialog.addEventListener('cancel',event=>{event.preventDefault();event.stopPropagation();});
 window.openReviewModal=()=>{
  if(!dialog.open){returnFocus=document.activeElement;review.hidden=false;dialog.showModal();}
  document.documentElement.classList.add('review-modal-open');document.body.classList.add('review-modal-open');
  const toast=document.getElementById('toast');if(toast&&toast.parentNode!==dialog)dialog.append(toast);
  for(const panel of review.querySelectorAll('.review-board-panel,.review-info-panel'))panel.scrollTop=0;
  review.scrollTop=0;document.getElementById('close-review').focus({preventScroll:true});
 };
 window.closeReviewModal=()=>{
  document.getElementById('promotion-chooser')?.remove();dialog.querySelector('.piece-ghost')?.remove();
  if(dialog.open)dialog.close();review.hidden=true;
  if(typeof S!=='undefined'){S.review=null;S.scenario=null;S.practicing=false;S.selected=null;S.reviewTeacherToken=(S.reviewTeacherToken||0)+1;}
  document.documentElement.classList.remove('review-modal-open');document.body.classList.remove('review-modal-open');
  const toast=document.getElementById('toast');if(toast)document.body.prepend(toast);
  if(returnFocus?.isConnected)returnFocus.focus?.({preventScroll:true});returnFocus=null;
 };
 document.getElementById('close-review').addEventListener('click',window.closeReviewModal);
})();
