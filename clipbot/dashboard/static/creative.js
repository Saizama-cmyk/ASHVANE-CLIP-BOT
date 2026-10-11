"use strict";
/* Feedback belongs to the output's business, client/style or named account. */
(() => {
  const widgets=[],accounts={};let next=0;
  window.addEventListener('accountprofilechange',event=>{
    const {business,profile_id}=event.detail||{};if(!business||!profile_id)return;
    accounts[business]=profile_id;
    widgets.filter(widget=>widget.business===business).forEach(widget=>widget.setAccount(profile_id));
  });
  window.creativeMemory={
    hasUnsaved:business=>widgets.some(widget=>widget.business===business&&widget.dirty()),
    mount(target,{business,scope={},example=()=>({}),label='creative drafts',followAccount=true}){
      const id='creative-'+(++next);
      let current={...scope},notesDirty=false,guidanceDirty=false,loaded=false,working=false,epoch=0,noteExample=null,pending=null,scopePromise=null;
      if(business!=='social'&&accounts[business])current.account_profile_id=accounts[business];
      target.classList.add('creative-feedback');
      target.innerHTML=`<div class="creative-feedback-head"><strong>Guide the next draft</strong><span>Saved feedback improves future direction.</span></div><label for="${id}-notes">What worked, or what should change?</label><textarea id="${id}-notes" name="${id}_notes" rows="2" maxlength="6000" placeholder="Be specific about the idea, words, pacing or style"></textarea><div class="creative-feedback-actions"><button class="btn" type="button" data-verdict="liked">Keep this direction</button><button class="btn" type="button" data-verdict="disliked">Change this direction</button></div><details><summary>Saved creative guidance</summary><label for="${id}-guidance">Saved direction · ${esc(label)}</label><textarea id="${id}-guidance" name="${id}_guidance" rows="4" maxlength="8000"></textarea><button class="btn" type="button" data-save-guidance>Save guidance</button></details><p class="creative-feedback-status" role="status" aria-live="polite"></p>`;
      const notes=target.querySelector(`#${id}-notes`),guidance=target.querySelector(`#${id}-guidance`),status=target.querySelector('[role=status]'),details=target.querySelector('details');
      const say=(text,error=false)=>{status.textContent=text;status.classList.toggle('error',error);};
      const dirty=()=>notesDirty||guidanceDirty;
      const query=()=>{const q=new URLSearchParams(Object.entries(current).filter(([,value])=>value));return q.size?'?'+q:'';};
      async function request(suffix='',options={}){
        const result=await api('/api/creative-memory/'+business+suffix,options);
        if(!result.ok||result.body?.error)throw new Error(typeof result.body?.detail==='string'?result.body.detail:result.body?.error||'Creative guidance could not be saved. Retry when this PC is ready.');
        return result.body;
      }
      function captureIdentity(memory){if(business!=='social'&&memory.account_profile_id&&!current.account_profile_id)current.account_profile_id=memory.account_profile_id;}
      async function bind(){
        if(business==='social'||current.account_profile_id)return;
        if(!scopePromise)scopePromise=request(query()).then(captureIdentity).finally(()=>{scopePromise=null;});
        await scopePromise;
      }
      async function load(){
        if(loaded||guidanceDirty)return;
        const token=++epoch;say('Loading saved direction…');
        try{
          const memory=await request(query());if(token!==epoch)return;captureIdentity(memory);
          if(!guidanceDirty)guidance.value=memory.guidance||'';
          const references=memory.reference_guidance||[];
          let learning=target.querySelector('.creative-reference-learning');
          if(!learning){learning=document.createElement('div');learning.className='creative-reference-learning';details.append(learning);}
          learning.innerHTML=references.length?`<p>${references.length} saved reference${references.length===1?'':'s'} guide future drafts in this scope.</p>`+references.map(reference=>`<details><summary>${esc(reference.name||'Reference')} · ${esc(reference.status||'saved')}</summary><p>${esc(reference.summary||'')}</p>${(reference.rules||[]).map(rule=>`<p>${esc(rule)}</p>`).join('')}</details>`).join(''):'';
          loaded=true;say('Saved guidance is used by future local drafts.');
        }catch(error){if(token===epoch)say(error.message,true);}
      }
      function setScope(value){
        if(JSON.stringify(value)===JSON.stringify(current))return;
        if(dirty()||working){pending={...value};say('Unsaved feedback remains bound to its previous profile. Save it here before editing guidance for the newly selected profile.');return;}
        current={...value};pending=null;++epoch;loaded=false;noteExample=null;notes.value=guidance.value='';target.querySelector('.creative-reference-learning')?.remove();say('');if(details.open)load();
      }
      notes.addEventListener('focus',()=>bind().catch(error=>say(error.message,true)));
      notes.oninput=event=>{event.stopPropagation();notesDirty=true;noteExample=example();say('Feedback notes are unsaved. Choose a direction below to save them.');};
      guidance.oninput=event=>{event.stopPropagation();guidanceDirty=true;say('Unsaved creative guidance.');};
      details.addEventListener('toggle',()=>{if(details.open)load();});
      target.addEventListener('click',async event=>{
        const button=event.target.closest('[data-verdict],[data-save-guidance]');if(!button||working)return;
        working=true;target.querySelectorAll('button').forEach(b=>b.disabled=true);say('Saving creative direction…');
        try{
          await bind();
          if(button.hasAttribute('data-verdict')){
            const output=noteExample||example();
            await request('/feedback',{method:'POST',json:{...current,verdict:button.dataset.verdict,notes:notes.value,example:{title:String(output?.title||'').slice(0,200),text:String(output?.text||'').slice(0,12000)}}});
            notesDirty=false;noteExample=null;notes.value='';loaded=false;
            if(!guidanceDirty&&details.open)await load();say('Feedback saved for future drafts in this workspace.');
          }else{
            await request('',{method:'PUT',json:{...current,guidance:guidance.value}});guidanceDirty=false;loaded=true;say('Creative guidance saved.');
          }
        }catch(error){say(error.message,true);}
        finally{working=false;target.querySelectorAll('button').forEach(b=>b.disabled=false);if(pending&&!dirty())setScope(pending);}
      });
      const widget={business,dirty,setScope,setAccount(profile_id){if(business!=='social'&&followAccount)setScope({...current,account_profile_id:profile_id});},load,refresh(){loaded=false;return load();}};
      widgets.push(widget);return widget;
    }
  };
})();
