"use strict";
/* Shared supervisor controls. Every count, node and event comes from the engine. */
(() => {
  const get=id=>document.getElementById(id), root=get('view-supervisor');
  if(!root)return;
  let snapshot=null, selected='', loading=false, mutation=false, timer=0, lastRender='', loadPromise=null, generation=0;
  let neural=null, neuralPromise=null;
  const text=value=>typeof value==='string'?value:typeof value==='number'?String(value):'';
  const label=value=>text(value).replace(/[_-]/g,' ');
  const rows=value=>Array.isArray(value)?value:value&&typeof value==='object'?Object.entries(value).map(([id,row])=>typeof row==='object'&&row&&!Array.isArray(row)?{id,...row}:{id,name:id,value:row}):[];
  const safe=value=>esc(text(value));
  const stamp=value=>{if(!value)return '';const date=new Date(typeof value==='number'?value*1000:value);return Number.isNaN(date.getTime())?'':date.toLocaleString();};
  async function request(path,options={}){const r=await api(path,options);if(!r.ok||r.body?.ok===false)throw new Error(typeof r.body?.detail==='string'?r.body.detail:r.body?.error||`Supervisor request failed (${r.status}).`);return r.body;}
  function notice(message,error=false){get('supervisorNotice').hidden=!message;get('supervisorNoticeText').textContent=message;get('supervisorNotice').classList.toggle('error',error);get('supervisorRailError').textContent=error?message:'';get('supervisorRailError').hidden=!error;}
  function controls(){root.querySelectorAll('[data-supervisor-dataset]').forEach(button=>button.disabled=mutation||!(snapshot?.examples?.[button.dataset.supervisorDataset]>0));root.querySelectorAll('[data-supervisor-rollback]').forEach(button=>button.disabled=mutation||!!(snapshot?.active_job||snapshot?.pending_job));const known=!!snapshot,enabled=snapshot?.enabled===true,active=!!(snapshot?.active_job||snapshot?.pending_job);get('supervisorMaster').disabled=!known||mutation;get('supervisorMaster').setAttribute('aria-checked',String(enabled));get('supervisorMasterState').textContent=mutation?'Saving...':known?enabled?'Enabled':'Off':'Connecting...';get('supervisorRun').disabled=!known||!enabled||active||mutation;get('supervisorCancel').disabled=!active||mutation;get('supervisorRunHelp').textContent=!known?'Waiting for the supervisor engine.':!enabled?'Turn on the master switch to run improvement work.':active?'A job is already active. You can cancel it below.':'Start the next improvement cycle, or give the supervisor a specific goal.';}
  function taskSummary(value){
    if(!value)return 'No current task reported.';
    if(typeof value!=='string')return text(value);
    try{
      const parsed=JSON.parse(value);
      if(!parsed||typeof parsed!=='object'||Array.isArray(parsed))return value;
      const direction=text(parsed.owner_goal||parsed.task);
      const observations=parsed.observations;
      const parts=[];
      if(direction)parts.push(direction);
      else if(parsed.verified_capabilities)parts.push('Director is checking installed capabilities and observed work.');
      if(observations&&typeof observations==='object'){
        if(observations.business_generation_active===true)parts.push('Business generation is active.');
        if(typeof observations.clip_jobs_in_flight==='number')parts.push(`${observations.clip_jobs_in_flight} clip jobs in flight.`);
      }
      return parts.join(' ')||'A task is reported; no owner-facing description is available.';
    }catch(_){return value;}
  }
  function inspect(){
    const agent=rows(snapshot?.agents).find(row=>row.id===selected);
    const inspector=get('supervisorInspector');
    if(!agent){
      inspector.innerHTML='<h3>Inspect an agent</h3><p>Select an agent to read its reported status, task and latest ledger record.</p>';
    }else{
      const latest=rows(snapshot?.events).filter(row=>row.role===selected).at(-1);
      const goal=rows(snapshot?.goals).filter(row=>row.agent===selected).at(-1);
      const waiting=snapshot?.state==='waiting_for_business';
      const status=waiting?'Available · waiting for business work':label(agent.status)||'Not reported';
      const task=waiting?'No supervisor work running while a business owns the workstation.':taskSummary(agent.task);
      const latestAt=latest?stamp(latest.at):'';
      const goalAt=goal?stamp(goal.created_at):'';
      inspector.innerHTML=`<p>Agent inspection</p><h3>${safe(agent.name||agent.id)}</h3><dl><dt>Status</dt><dd>${safe(status)}</dd><dt>Current task</dt><dd>${safe(task)}</dd><dt>Role</dt><dd>${safe(agent.instructions||'No role instructions reported.')}</dd>${goal?`<dt>Latest delegated goal</dt><dd>${safe(goal.goal||'No goal text reported.')}${goalAt?`<small>Recorded ${safe(goalAt)}</small>`:''}</dd>`:''}${latest?`<dt>Latest recorded event</dt><dd><strong>${safe(label(latest.kind)||'Event')}</strong>${latest.summary?' · '+safe(latest.summary):''}${typeof latest.passed==='boolean'?' · '+(latest.passed?'passed':'failed'):''}${latestAt?`<small>Recorded ${safe(latestAt)}</small>`:''}</dd>`:''}${agent.model?`<dt>Model</dt><dd>${safe(agent.model)}</dd>`:''}${agent.error?`<dt>Last error</dt><dd>${safe(agent.error)}</dd>`:''}</dl>`;
    }
    root.querySelectorAll('[data-supervisor-agent]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.supervisorAgent===selected)));
  }
  function ensureNeural(stage){
    if(neural||neuralPromise||!root.classList.contains('active'))return;
    neuralPromise=import('/static/supervisor-neural.js?v=0712e86a8e67f695').then(module=>{
      if(!stage.isConnected)return;
      neural=module.create(stage,{onSelect:id=>{selected=id;inspect();neural?.setSelected(id);},onStatus:state=>{stage.classList.toggle('is-rendered',state==='ready');const note=stage.querySelector('.supervisor-neural-fallback');if(note)note.textContent=state==='paused'?'3D view paused while graphics recover. Agent controls and records remain available.':'Local 3D view ready.';}});
      if(snapshot)neural.update(snapshot,selected);
      window.ashvaneCoreCamera=action=>{if(action==='reset')neural?.resetCamera();else neural?.zoom(action==='in'?-.12:.12);};
      const cameraTools=document.createElement('div');cameraTools.className='core-camera-tools';cameraTools.innerHTML='<button type="button" data-core-camera="out" aria-label="Zoom out">−</button><button type="button" data-core-camera="reset" aria-label="Reset Core camera">⌖</button><button type="button" data-core-camera="in" aria-label="Zoom in">+</button>';stage.append(cameraTools);
      const cameraNote=document.createElement('span');cameraNote.className='core-camera-note';cameraNote.textContent='Drag to orbit · select an agent · double-click to reset';stage.append(cameraNote);
      stage.classList.add('is-rendered');
    }).catch(error=>{
      stage.classList.add('is-unavailable');
      const note=stage.querySelector('.supervisor-neural-fallback');
      if(note)note.textContent='3D view unavailable. The live agent list and records remain below.';
      console.warn('Supervisor 3D view unavailable:',error);
    });
  }
  function network(){
    const agents=rows(snapshot?.agents), container=get('supervisorAgents');
    const focused=document.activeElement?.dataset?.supervisorAgent;
    get('supervisorRosterCount').textContent=`${agents.length} ${agents.length===1?'agent':'agents'} reported`;
    if(!agents.some(agent=>agent.id===selected))selected=agents[0]?.id||'';
    if(!agents.length){
      neural?.dispose();neural=null;neuralPromise=null;
      container.innerHTML='<p class="supervisor-map-empty">No agents have been reported yet. Refresh after the supervisor engine is available.</p>';
      inspect();return;
    }
    if(!container.querySelector('.supervisor-neural-stage')){
      container.innerHTML='<div class="supervisor-neural-stage"><div class="supervisor-neural-label"><span>ASHVANE · SHARED SUPERVISOR</span><strong>One core. Real specialist branches.</strong></div><div class="supervisor-neural-fallback" aria-live="polite">Loading local 3D view…</div><div class="supervisor-neural-axis" aria-hidden="true">ROSTER / DELEGATION / RECORDED ACTION</div></div><div class="supervisor-network-key"><span>Dim branches: available roles</span><span>Light packet: new recorded event</span></div><div class="supervisor-flow-note"><strong>Possible improvement path</strong><span>Director → specialist → isolated Sandbox checks → independent reviewer → optional source application</span></div><div class="supervisor-role-grid" id="supervisorRoleGrid" aria-label="Supervisor agents"></div>';
    }
    const stage=container.querySelector('.supervisor-neural-stage');
    ensureNeural(stage);
    const waiting=snapshot?.state==='waiting_for_business';
    get('supervisorRoleGrid').innerHTML=agents.map((agent,index)=>{
      const id=safe(agent.id), name=safe(agent.name||agent.id), status=waiting?'Available · waiting for business work':safe(label(agent.status)||'Not reported');
      return `<button type="button" class="supervisor-role" data-supervisor-agent="${id}" data-role="${safe(agent.id)}" aria-pressed="${agent.id===selected}" aria-controls="supervisorInspector"><span class="supervisor-role-index">${String(index+1).padStart(2,'0')}</span><span><b>${name}</b><small>${status}</small></span><span class="supervisor-role-arrow" aria-hidden="true">↗</span></button>`;
    }).join('');
    if(focused)[...container.querySelectorAll('button')].find(button=>button.dataset.supervisorAgent===focused)?.focus({preventScroll:true});
    inspect();
  }
  function records(id,items,empty,kind){
    const list=rows(items);
    get(id).innerHTML=list.length?list.slice().reverse().slice(0,40).map(row=>{
      if(typeof row==='string')return `<li>${safe(row)}</li>`;
      const title=kind==='event'?label(row.role||row.kind):row.title||row.goal||row.name||row.id;
      const detail=row.detail||row.summary||row.error||row.task||row.result;
      const changed=row.change, rollback=kind==='job'&&(row.can_rollback===true||row.rollback_available===true||changed?.status==='source_applied');
      const date=stamp(row.finished_at||row.updated_at||row.created_at||row.started_at||row.at||row.timestamp);
      const changeInfo=changed?`<small>Change: ${safe(label(changed.status)||'Not reported')}${changed.restart_required?' · restart required':''}</small>${changed.checks?`<small>Checks: ${changed.checks.passed===true?'passed':changed.checks.passed===false?'failed':'not reported'}</small>`:''}${changed.review?`<small>Review: ${changed.review.passed===true?'passed':changed.review.passed===false?'failed':'not reported'}</small>`:''}`:'';
      return `<li><strong>${safe(title||'Record')}</strong>${detail?`<div>${safe(detail)}</div>`:''}${row.status||row.kind?`<small>${safe(label(row.status||row.kind))}${typeof row.passed==='boolean'?' · '+(row.passed?'passed':'failed'):''}</small>`:''}${kind==='goal'&&(row.agent||row.parent)?`<small>${row.agent?'Agent: '+safe(label(row.agent)):''}${row.parent?' · Parent: '+safe(row.parent):''}</small>`:''}${date?`<time>${safe(date)}</time>`:''}${changeInfo}${rollback?`<button class="btn" type="button" data-supervisor-rollback="${safe(changed?.candidate_id||row.id||row.job_id)}" ${mutation||(snapshot?.active_job||snapshot?.pending_job)?'disabled':''}>Roll back this change</button>`:''}</li>`;
    }).join(''):`<li class="supervisor-help">${safe(empty)}</li>`;
  }
  function describe(value,depth=0){
    if(value===true)return 'Yes';if(value===false)return 'No';
    if(typeof value==='string'||typeof value==='number')return text(value);
    if(Array.isArray(value))return value.map(item=>describe(item,depth+1)).filter(Boolean).join(', ');
    if(value&&typeof value==='object'&&depth<3)return Object.entries(value).map(([key,item])=>`${label(key)}: ${describe(item,depth+1)}`).join(' · ');
    return '';
  }
  function capabilities(id,value,empty){
    const names={models:'Installed models',decision_model:'Decision model',engineering_model:'Engineering model',isolation:'Host Sandbox checks',source:'Source access',public_research:'Public research',weight_training:'Model weight training',private_accounts:'Private account access',auto_apply:'Automatic source changes'};
    const list=rows(value).filter(row=>row.id!=='extensions');
    get(id).innerHTML=list.length?list.map(row=>typeof row==='string'?`<div>${safe(row)}</div>`:`<div><strong>${safe(row.label||names[row.id]||row.name||row.package||label(row.id))}</strong><br><span>${safe(row.value!==undefined?describe(row.value):describe(Object.fromEntries(Object.entries(row).filter(([key])=>!['id','name','label'].includes(key)))))}</span></div>`).join(''):`<p>${safe(empty)}</p>`;
  }
  function observations(){
    const value=snapshot?.observations, target=get('supervisorObservations');
    if(!value){target.textContent='Runtime evidence is not available from this engine yet.';return;}
    const metric=(number,unit='')=>typeof number==='number'&&Number.isFinite(number)?`${number}${unit}`:'Unavailable';
    const queue=value.queue||{}, gpu=value.resources?.gpu||{};
    target.innerHTML=`<p>${value.collecting?'Collecting runtime metadata.':'Collection stopped with the master switch.'}${value.inference_deferred?' Model work is waiting for business generation.':''}</p><dl class="supervisor-counts"><div><dt>Warnings / errors · ${safe(metric(value.window_min,' min'))}</dt><dd>${safe(metric(value.fault_events))}</dd></div><div><dt>Active clip jobs</dt><dd>${safe(metric(queue.active))}</dd></div><div><dt>Longest slot wait</dt><dd>${safe(metric(queue.longest_wait_s,' s'))}</dd></div><div><dt>GPU usage</dt><dd>${safe(metric(gpu.util,'%'))}</dd></div></dl><ol class="supervisor-records">${rows(value.faults).length?rows(value.faults).map(row=>`<li><strong>${safe(row.source)}:${safe(row.line)}</strong><div>${safe(row.count)} ${safe(row.severity)}${row.exception?' · '+safe(row.exception):''}</div><time>Last seen ${safe(stamp(row.last_at))}</time></li>`).join(''):'<li>No faults observed in this process and time window.</li>'}</ol>${value.bounded_sample?'<p>The event sample reached its limit; counts may omit older events.</p>':''}`;
  }
  function render(){controls();observations();const currentState=label(snapshot.state)||'Not reported';get('supervisorState').textContent=currentState;get('supervisorState').dataset.running=String(snapshot.enabled===true);const signature=JSON.stringify([snapshot.agents,snapshot.state]);if(signature!==lastRender){lastRender=signature;network();}else inspect();const stage=get('supervisorAgents').querySelector('.supervisor-neural-stage');if(stage)ensureNeural(stage);neural?.update(snapshot,selected);const job=snapshot.active_job||snapshot.pending_job;get('supervisorCurrent').innerHTML=job?`<strong>${safe(job.goal||job.title||job.id||'Active improvement job')}</strong><p>${safe(label(job.stage||job.status)||'In progress')}${job.task?'  /  '+safe(job.task):''}</p>${typeof job.progress==='number'?`<progress class="supervisor-progress" max="100" value="${Math.max(0,Math.min(100,job.progress))}" aria-label="Job progress"></progress>`:''}`:'<strong>No active job</strong><p>Completed work and reversible changes appear in Job history.</p>';records('supervisorEvents',snapshot.events,'No events yet. Supervisor activity will appear here.','event');records('supervisorGoals',snapshot.goals,'No saved goals have been reported. Give the next cycle a direction above.','goal');records('supervisorJobs',snapshot.jobs,'No jobs have been recorded yet.','job');for(const key of ['total','eligible','training','evaluation']){const n=snapshot.examples?.[key];get('supervisorCount-'+key).textContent=typeof n==='number'&&Number.isFinite(n)?String(n):'--';}capabilities('supervisorCapabilities',snapshot.capabilities,'Not checked yet. Start a cycle to probe local models, isolation and source access.');capabilities('supervisorExtensions',snapshot.extensions,'No extensions reported.');root.querySelectorAll('[data-supervisor-dataset]').forEach(button=>{const count=snapshot.examples?.[button.dataset.supervisorDataset];button.disabled=mutation||!(typeof count==='number'&&count>0);});if(snapshot.error)notice(text(snapshot.error),true);}
  function operations(){
    const target=get('coreOperations');if(!target)return;
    const receipts=rows(snapshot?.work_receipts),jobs=rows(snapshot?.jobs),block=snapshot?.blocking_reason;
    const known=Array.isArray(snapshot?.work_receipts),verified=jobs.filter(job=>job.change?.status==='source_applied').length;
    target.innerHTML=`<div class="core-identity"><span>ASHVANE / SHARED INTELLIGENCE</span><h2>A mind for the machinery.</h2><p>Trace a decision from observation to evidence, test, review and a reversible change.</p></div><div class="core-operational-state" data-blocked="${!!block?.code}"><span class="core-status-light"></span><div><strong>${safe(block?.reason||label(snapshot?.state)||'Waiting for runtime')}</strong><p>${snapshot?.next_cycle_at?'Next scheduled cycle '+safe(stamp(snapshot.next_cycle_at)):snapshot?.enabled?'Local agents are enabled.':'Enable the master switch to start Core.'}</p></div></div><dl class="core-metrics"><div><dt>Recorded tool outcomes</dt><dd>${known?receipts.length:'—'}</dd></div><div><dt>Recorded cycles</dt><dd>${jobs.length}</dd></div><div><dt>Applied changes</dt><dd>${verified}</dd></div><div><dt>Eligible examples</dt><dd>${typeof snapshot?.examples?.eligible==='number'?snapshot.examples.eligible:'—'}</dd></div></dl><div class="core-protocol" aria-label="Improvement workflow"><a href="#core-evidence">01 Observe</a><span>→</span><a href="#core-evidence">02 Investigate</a><span>→</span><a href="#core-history">03 Test</a><span>→</span><a href="#core-history">04 Review</a><span>→</span><a href="#core-history">05 Apply / roll back</a></div><details class="core-receipts" id="core-evidence"><summary>Tool outcome receipts <span>${known?receipts.length:'Not reported'}</span></summary><ol>${receipts.length?receipts.slice(-16).reverse().map(row=>`<li><span>${safe(label(row.role))}</span><strong>${safe(label(row.action||row.kind))} · ${safe(label(row.outcome))}</strong><p>${safe(row.summary||'')}</p><time>${safe(stamp(row.at))}</time></li>`).join(''):'<li>No tool outcomes reported. Requests and ambient movement do not count as tool results.</li>'}</ol></details>`;
    get('supervisorJobs')?.closest('section')?.setAttribute('id','core-history');
  }
  function load(force=false){
    if(loading)return force?loadPromise.then(()=>load()):loadPromise;
    loading=true;get('supervisorRefresh').disabled=true;const version=generation;
    loadPromise=(async()=>{try{
      const result=await request('/api/supervisor');
      if(version!==generation)return false;
      snapshot=result;render();operations();if(!snapshot.error&&!mutation)notice('');return true;
    }catch(error){if(version===generation)notice(error.message,true);controls();return false;
    }finally{loading=false;get('supervisorRefresh').disabled=false;clearTimeout(timer);if(!document.hidden)timer=setTimeout(()=>load(),root.classList.contains('active')?4000:15000);}})();
    return loadPromise;
  }
  async function mutate(path,payload,pending,success){
    if(mutation)return false;mutation=true;++generation;controls();notice(pending);
    try{const result=await request(path,{method:'POST',json:payload});if(typeof result?.enabled==='boolean'&&Array.isArray(result.agents)){snapshot=result;render();}if(await load(true)){if(!snapshot.error)notice(success);}return true;
    }catch(error){notice(error.message,true);return false;}finally{mutation=false;controls();}
  }
  root.addEventListener('click',event=>{const link=event.target.closest('.core-protocol a');if(!link)return;event.preventDefault();const target=get(link.getAttribute('href').slice(1));if(target){if(target.tagName==='DETAILS')target.open=true;target.scrollIntoView({behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});}});
  get('supervisorMaster').addEventListener('click',()=>mutate('/api/supervisor/master',{enabled:!snapshot?.enabled},snapshot?.enabled?'Stopping supervisor work and saving master switch...':'Enabling supervisor and saving master switch...',snapshot?.enabled?'Master switch is off. The engine is cancelling or draining active work.':'Master switch is enabled.'));
  get('supervisorGoalForm').addEventListener('submit',async event=>{event.preventDefault();if(get('supervisorRun').disabled)return;const goal=get('supervisorGoal').value.trim();if(await mutate('/api/supervisor/run',goal?{goal}:{},'Starting improvement cycle...','Improvement cycle requested.'))get('supervisorGoal').value='';});
  get('supervisorCancel').addEventListener('click',()=>mutate('/api/supervisor/cancel',{},'Requesting cancellation...','Cancellation requested. Waiting for the active job to stop.'));
  get('supervisorRefresh').addEventListener('click',()=>load());
  get('supervisorAgents').addEventListener('click',event=>{const button=event.target.closest('[data-supervisor-agent]');if(button){selected=button.dataset.supervisorAgent;inspect();neural?.setSelected(selected);}});
  get('supervisorJobs').addEventListener('click',async event=>{const button=event.target.closest('[data-supervisor-rollback]');if(!button||mutation)return;if(!await ask({title:'Roll back this supervisor job?',body:'Restore the previous version of changes recorded by this job. The engine checks whether rollback is still available.',ok:'Roll back job',danger:true}))return;button.disabled=true;await mutate('/api/supervisor/rollback',{job_id:button.dataset.supervisorRollback},'Rolling back recorded changes...','Rollback requested.');if(button.isConnected)button.disabled=false;});
  root.querySelectorAll('[data-supervisor-dataset]').forEach(button=>button.addEventListener('click',async()=>{button.disabled=true;notice('Preparing dataset download...');let url;try{const response=await fetch('/api/supervisor/dataset/'+button.dataset.supervisorDataset,{credentials:'same-origin',headers:{'X-ClipBot':'1'}});if(!response.ok){let body={};try{body=await response.json();}catch(_){}throw new Error(typeof body.detail==='string'?body.detail:`Dataset download failed (${response.status}).`);}url=URL.createObjectURL(await response.blob());const anchor=document.createElement('a');anchor.href=url;anchor.download=`ashvane-${button.dataset.supervisorDataset}.jsonl`;document.body.append(anchor);anchor.click();anchor.remove();notice('Dataset downloaded.');}catch(error){notice(error.message,true);}finally{if(url)setTimeout(()=>URL.revokeObjectURL(url),1000);button.disabled=!(snapshot?.examples?.[button.dataset.supervisorDataset]>0);}}));
  document.addEventListener('visibilitychange',()=>{clearTimeout(timer);if(!document.hidden)load();});
  window.loadSupervisor=load;controls();load();
})();
