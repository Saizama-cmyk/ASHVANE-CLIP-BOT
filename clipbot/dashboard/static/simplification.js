"use strict";
/* Progressive disclosure preserves existing fields, form ownership and handlers. */
(() => {
  const manage=document.getElementById('surgeManage'),badge=document.getElementById('setupCount'),mirror=document.getElementById('manageSetupCount');
  const managed=new Set(['system','settings','setup']);
  function roving(){
    document.querySelectorAll('nav[role=tablist]').forEach(nav=>{
      const tabs=[...nav.querySelectorAll('button[role=tab]')],visible=tabs.filter(tab=>!nav.hidden&&!tab.closest('details:not([open])'));
      const current=visible.find(tab=>tab.getAttribute('aria-selected')==='true')||visible[0];
      tabs.forEach(tab=>tab.tabIndex=tab===current?0:-1);
      nav.setAttribute('aria-orientation',innerWidth<=640?'horizontal':'vertical');
    });
  }
  function sync(view){if(manage&&managed.has(view))manage.open=true;roving();}
  function setupBadge(){if(!badge||!mirror)return;mirror.hidden=badge.hidden;mirror.textContent=badge.textContent;mirror.title=badge.hidden?'':'Setup items need attention';}
  manage?.addEventListener('toggle',roving);
  document.addEventListener('invalid',event=>{let details=event.target.closest('details');while(details){details.open=true;details=details.parentElement?.closest('details');}},true);
  window.addEventListener('resize',roving);
  window.syncWorkspaceNavigation=sync;
  if(typeof MutationObserver!=='undefined'&&badge)new MutationObserver(setupBadge).observe(badge,{attributes:true,childList:true,characterData:true,subtree:true});
  setupBadge();sync(document.querySelector('section.view.active')?.id.replace('view-',''));
})();
