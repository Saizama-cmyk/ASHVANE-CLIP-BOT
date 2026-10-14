"use strict";
/* The frame is artwork. Business switches and Core outcomes remain engine-owned. */
(() => {
  const brand=document.querySelector('.brand span');if(brand)brand.textContent='The living observatory';
  const hint=document.getElementById('lockHint');if(hint)hint.textContent='Four ventures. One direction. Your local observatory.';
  if(!window.matchMedia('(prefers-reduced-motion: reduce)').matches){
    const reveal=document.createElement('div');reveal.className='observatory-launch';reveal.setAttribute('aria-hidden','true');
    reveal.innerHTML='<div><img src="/static/art/ashvane-mark.svg" width="100" height="100" alt=""><h2>ASHVANE</h2><p>THE LIVING OBSERVATORY</p></div>';
    document.body.append(reveal);reveal.addEventListener('animationend',()=>reveal.remove(),{once:true});
    setTimeout(()=>reveal.remove(),1800);
  }
  document.addEventListener('click',event=>{const action=event.target.closest('[data-core-camera]');if(action)window.ashvaneCoreCamera?.(action.dataset.coreCamera);});
})();
