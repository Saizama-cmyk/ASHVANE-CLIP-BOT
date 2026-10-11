"use strict";
/* Original procedural lensing study. The actual live shell moves, no captured UI image. */
(() => {
  const shell=document.querySelector('.shell'), originalShow=show;
  let current=document.querySelector('section.view.active')?.id.replace('view-','')||'clips', transition=null;
  function finish(){if(transition){transition.cancel();transition=null;}}
  function immediate(view){originalShow(view);current=PAGES[view]?view:'clips';document.body.classList.toggle('story-mode',current==='stories');if(current==='stories'&&window.loadStories)window.loadStories();document.querySelector(`nav [data-view="${current}"]`)?.scrollIntoView({block:'nearest',inline:'nearest'});}
  function portal(view){
    finish();
    const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
    if(reduced||!shell.animate){immediate(view);shell.animate?.([{opacity:.6},{opacity:1}],{duration:100,easing:'ease-out'});return;}
    const overlay=document.createElement('div');overlay.className='story-portal';overlay.setAttribute('aria-hidden','true');const canvas=document.createElement('canvas');overlay.append(canvas);document.body.append(overlay);
    const ctx=canvas.getContext('2d');if(!ctx){overlay.remove();immediate(view);return;}
    const w=innerWidth,h=innerHeight,dpr=Math.min(devicePixelRatio||1,1.5);canvas.width=w*dpr;canvas.height=h*dpr;ctx.scale(dpr,dpr);
    const x=w/2,y=h/2+scrollY;document.body.style.setProperty('--portal-x',`${x}px`);document.body.style.setProperty('--portal-y',`${y}px`);document.body.classList.add('story-portal-active');
    let raf=0, cancelled=false, swapped=false, first=null, second=null;
    const particles=Array.from({length:110},(_,i)=>({angle:i*2.399963,r:.2+(i%31)/31,alpha:.25+(i%7)/10,size:i%9===0?1.4:.65}));
    const start=performance.now(), duration=1240;
    function draw(now){if(cancelled)return;const t=Math.min(1,(now-start)/duration),opening=t>.49,p=opening?(1-t)/.51:t/.49,strength=Math.sin(Math.PI*Math.min(1,p)/2),cx=w/2,cy=h/2,r=Math.max(24,Math.min(w,h)*.145);
      ctx.clearRect(0,0,w,h);ctx.fillStyle=`rgba(2,4,8,${strength*.94})`;ctx.fillRect(0,0,w,h);ctx.save();ctx.translate(cx,cy);
      for(const a of particles){const radius=(Math.max(w,h)*a.r)*(1-strength*.88);const angle=a.angle+t*2.7;ctx.strokeStyle=`rgba(210,225,239,${a.alpha*strength*.65})`;ctx.lineWidth=a.size;ctx.beginPath();ctx.moveTo(Math.cos(angle)*radius,Math.sin(angle)*radius*.7);ctx.lineTo(Math.cos(angle+.07*strength)*radius*(1+.2*strength),Math.sin(angle+.07*strength)*radius*.7*(1+.2*strength));ctx.stroke();}
      ctx.rotate(-.18);ctx.globalAlpha=strength;
      const glow=ctx.createRadialGradient(0,0,r*.5,0,0,r*2.3);glow.addColorStop(0,'#00000000');glow.addColorStop(.3,'#D9965211');glow.addColorStop(.6,'#DAA66B1C');glow.addColorStop(1,'#00000000');ctx.fillStyle=glow;ctx.fillRect(-r*3,-r*3,r*6,r*6);
      for(let i=35;i>=0;i--){const rr=r*(.76+i*.032);ctx.lineWidth=i<5?1.2:.65;ctx.strokeStyle=`rgba(${i%4===0?'244,220,188':'218,166,107'},${.16+(35-i)/80})`;ctx.beginPath();ctx.ellipse(0,0,rr,rr*(.18+i*.003),0,Math.PI,Math.PI*2);ctx.stroke();}
      // Light from the far side bends over the event horizon instead of forming a flat planet ring.
      for(let i=18;i>=0;i--){ctx.strokeStyle=`rgba(244,220,188,${.04+(18-i)*.007})`;ctx.lineWidth=.9;ctx.beginPath();ctx.ellipse(0,-r*.025,r*(.81+i*.012),r*(.83+i*.011),0,Math.PI,Math.PI*2);ctx.stroke();}
      ctx.fillStyle='#010205';ctx.beginPath();ctx.arc(0,0,r*.72,0,Math.PI*2);ctx.fill();
      for(let i=14;i>=0;i--){ctx.strokeStyle=`rgba(244,220,188,${.035+(14-i)*.015})`;ctx.lineWidth=i<3?1.2:.7;ctx.beginPath();ctx.arc(0,0,r*(.72+i*.007),0,Math.PI*2);ctx.stroke();}
      for(let i=35;i>=0;i--){const rr=r*(.76+i*.032);ctx.strokeStyle=`rgba(${i%5===0?'244,220,188':'218,166,107'},${.2+(35-i)/65})`;ctx.lineWidth=i<5?1.3:.7;ctx.beginPath();ctx.ellipse(0,0,rr,rr*(.18+i*.003),0,0,Math.PI);ctx.stroke();}
      ctx.restore();if(t<1)raf=requestAnimationFrame(draw);
    }
    const cleanup=()=>{if(cancelled)return;cancelled=true;cancelAnimationFrame(raf);first?.cancel();second?.cancel();overlay.remove();document.body.classList.remove('story-portal-active');shell.style.removeProperty('transform');shell.style.removeProperty('opacity');shell.style.removeProperty('filter');if(transition?.cancel===cleanup)transition=null;};
    transition={cancel:cleanup};raf=requestAnimationFrame(draw);
    first=shell.animate([{transform:'perspective(1100px) scale(1) rotate(0deg)',opacity:1},{transform:'perspective(1100px) scale(.56,.45) rotate(-8deg)',opacity:.92,offset:.48},{transform:'perspective(1100px) scale(.012,.002) rotate(-58deg)',opacity:0}],{duration:590,easing:'cubic-bezier(.4,0,.82,.45)',fill:'forwards'});
    first.finished.then(()=>{if(cancelled)return;swapped=true;immediate(view);first.cancel();second=shell.animate([{transform:'perspective(1100px) scale(.012,.002) rotate(48deg)',opacity:0},{transform:'perspective(1100px) scale(.72,.64) rotate(5deg)',opacity:.85,offset:.5},{transform:'perspective(1100px) scale(1) rotate(0deg)',opacity:1}],{duration:650,easing:'cubic-bezier(.16,1,.3,1)',fill:'forwards'});return second.finished;}).then(()=>{if(cancelled)return;cleanup();document.getElementById('pageTitle')?.setAttribute('tabindex','-1');document.getElementById('pageTitle')?.focus({preventScroll:true});}).catch(()=>{if(!cancelled){if(!swapped)immediate(view);cleanup();}});
  }
  show=function(view){view=PAGES[view]?view:'clips';if(view===current&&!transition)return;const cross=(current==='stories')!==(view==='stories');if(cross)portal(view);else{finish();immediate(view);}};
  const skip=document.createElement('a');skip.className='cosmic-skip';skip.href='#workspace';skip.textContent='Skip to workspace';skip.addEventListener('click',e=>{e.preventDefault();document.getElementById('workspace').focus();});document.body.prepend(skip);
  const subtitle=document.querySelector('.brand span');if(subtitle)subtitle.textContent='Independent media observatory';
  immediate(current);
  window.addEventListener('pagehide',finish);window.addEventListener('resize',()=>{if(transition){finish();immediate(current);}});
})();
