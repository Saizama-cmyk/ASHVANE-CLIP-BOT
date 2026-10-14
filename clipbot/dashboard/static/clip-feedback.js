"use strict";
/* Owner corrections stay private; these controls never publish or override a verdict. */
(() => {
  const panel=document.getElementById('pvFeedback');if(!panel)return;
  let version=0,clip=null,working=false;
  async function request(method,payload){const response=await api('/api/clip-feedback/'+encodeURIComponent(clip.id),{method,headers:{'X-Account-Profile':clip.source?.account_profile_id||'default'},...(payload?{json:payload}:{})});if(!response.ok)throw new Error(response.body?.detail||'Clip feedback could not be saved.');return response.body;}
  function state(message,error=false){const note=panel.querySelector('[data-feedback-status]');if(note){note.textContent=message;note.classList.toggle('rejected',error);}}
  async function load(){
    const current=++version;working=true;
    panel.innerHTML='<h3>Your verdict</h3><p role="status">Loading this profile’s saved feedback…</p>';
    try{
      const result=await request('GET');if(current!==version)return;
      const record=result.record;
      panel.innerHTML=`<h3>Your verdict</h3><p>Was this moment worth posting? Save a correction for future evaluation. It stays private after media cleanup.</p><label for="clipFeedbackNote">Optional note</label><textarea id="clipFeedbackNote" rows="2" maxlength="${Number(result.note_limit)||0}" placeholder="For example: the quiet reaction at 12 seconds is the payoff."></textarea><div class="copyrow"><button class="btn" type="button" data-feedback="good" aria-pressed="${record?.label==='good'}">Worth posting</button><button class="btn" type="button" data-feedback="bad" aria-pressed="${record?.label==='bad'}">Not worth posting</button></div><p data-feedback-status role="status" aria-live="polite">${record?'Saved: '+esc(record.label==='good'?'worth posting':'not worth posting')+'. '+esc(record.split)+' sample.':'Add a note if useful, then choose a verdict to save.'}</p><small>${Number(result.summary.total)||0} saved corrections · ${Number(result.summary.wrong_rejections)||0} marked as wrong rejections. Saving feedback does not post a clip or change judge thresholds.</small>`;
      panel.querySelector('textarea').value=record?.note||'';
    }catch(error){if(current===version){panel.innerHTML='<h3>Your verdict</h3><p data-feedback-status role="status"></p><button class="btn" type="button" data-feedback-retry>Retry</button>';state(error.message,true);}}
    finally{if(current===version)working=false;}
  }
  panel.addEventListener('click',async event=>{
    if(event.target.closest('[data-feedback-retry]')){if(!working)load();return;}
    const button=event.target.closest('[data-feedback]');if(!button||working||!clip)return;
    const current=version;working=true;panel.querySelectorAll('button').forEach(item=>item.disabled=true);state('Saving your verdict…');
    const video=document.getElementById('pvVideo'),time=video?.currentTime;
    const duration=Math.max(0,(clip.end_wall||0)-(clip.start_wall||0));
    const payload={label:button.dataset.feedback,note:panel.querySelector('textarea').value,preview_s:Number.isFinite(time)&&time<=duration?time:null};
    try{await request('PUT',payload);if(current===version){working=false;await load();}}
    catch(error){if(current===version)state(error.message,true);}
    finally{if(current===version){working=false;panel.querySelectorAll('button').forEach(item=>item.disabled=false);}}
  });
  const previous=openPreview;
  openPreview=function(id){previous(id);clip=deskClips().find(row=>row.id===id);if(clip)load();};
  document.getElementById('preview').addEventListener('close',()=>{++version;working=false;});
  window.addEventListener('accountprofilechange',event=>{if(event.detail?.business==='clips'&&document.getElementById('preview').open&&clip)load();});
})();
