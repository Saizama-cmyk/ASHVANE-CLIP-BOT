"use strict";
/* The Stories studio reads its own engine state; clip candidates never enter this flow. */
(() => {
  const byId = id => document.getElementById(id);
  let data = null, selected = null, edited = false, manuscriptChanged = false;
  let scenes = [], fetching = false, sending = false, initialized = false, publication = null, publicationEdited = false;
  const working = new Set(["queued","directing","writing","judging","narrating","rendering"]);
  const names = {queued:"Queued",directing:"Directing",writing:"Writing manuscript",judging:"Reviewing story",draft:"Draft ready",needs_review:"Needs review",narrating:"Recording narration",rendering:"Rendering scenes",ready:"Video ready",failed:"Needs attention",interrupted:"Interrupted",cancelled:"Cancelled"};
  function message(id, value) { const el=byId(id); el.textContent=value||""; el.hidden=!value; }
  function errorText(body) { const v=body?.detail||body?.error||"The engine could not complete that request."; return typeof v==="string"?v:JSON.stringify(v); }
  async function request(path, options={}) { const r=await api(path,options); if(!r.ok)throw new Error(errorText(r.body)); return r.body; }
  function projectBody(body) { return body?.project||body; }
  function project() { return data?.projects?.find(p=>p.id===selected)||null; }
  function active(p) { return !!p && working.has(p.status); }
  function label(value) { return names[value]||String(value||"Draft").replaceAll("_"," "); }
  function genreName(id) { return data?.genres?.find(g=>g.id===id)?.label||String(id||"Horror").replaceAll("_"," "); }
  function putProject(p) { if(!p?.id)return; data.projects=[p,...(data.projects||[]).filter(v=>v.id!==p.id)]; }
  function selectedDestinations() { return [...document.querySelectorAll('[name="story_destination"]:checked')].map(el=>el.value); }
  function publicData(p) { return p?.public_copy?.youtube||p?.public_copy||{}; }
  function updateDirty(value=true) { edited=value; byId("storiesSave").disabled=!value||sending; byId("storiesDiscard").disabled=!value||sending; byId("storiesSaveMessage").textContent=value?"Unsaved changes":"Saved on this PC"; renderControls(); }
  function renderControls() {
    const p=project(), caps=data?.capabilities||{}, busy=active(p), canRender=!!caps.render_available;
    byId("storiesCreate").disabled=!data||sending||!!data.busy;
    byId("storiesCreate").textContent=sending?"Working…":data?.busy?"Another story is in production":"Create story draft";
    byId("storiesRender").disabled=!p||busy||!!data?.busy||sending||edited||!canRender||!p.script;
    byId("storiesRenderReason").textContent=edited?"Save your edits before rendering.":busy?"Production is running. You can cancel below.":data?.busy?"Another story is using the production engine.":!canRender?(caps.reasons?.join(" ")||"Configure a narrator and visual provider in Story settings."):!p?.script?"A completed manuscript is needed before rendering.":"Render this saved manuscript with its scene direction and chosen narrator.";
    byId("storiesCancel").hidden=!busy; byId("storiesRetry").hidden=!p||!["failed","interrupted","cancelled"].includes(p.status);
    byId("storiesDelete").disabled=busy||sending;
    byId("storiesReview").disabled=!p||busy||!!data?.busy||sending||edited||!p.script;
    const publish=byId("storiesPublishNow"); if(publish)publish.disabled=!p||p.status!=="ready"||edited||sending||!selectedDestinations().length;
  }
  function renderLibrary() {
    const all=data?.projects||[], query=byId("storiesLibrarySearch").value.trim().toLowerCase();
    const list=all.filter(p=>`${p.title||""} ${p.topic||""} ${p.genre||""}`.toLowerCase().includes(query));
    byId("storiesLibraryCount").textContent=`${all.length} saved`;
    byId("storiesLibrary").innerHTML=list.length?list.map(p=>`<button type="button" class="story-library-item" data-story-id="${esc(p.id)}" aria-current="${p.id===selected}"><strong>${esc(p.title||"Untitled story")}</strong><span class="story-library-meta">${esc(genreName(p.genre))} · ${p.format==="animated"?"Animated":"Illustrated"} · ${esc(p.duration_s)}s</span><span class="stories-status ${esc(p.status)}">${esc(label(p.status))}</span></button>`).join(""):`<p class="stories-library-empty">${query?"No stories match this search. Try another title or genre.":"Your first story starts with a premise above. Completed drafts and videos stay here."}</p>`;
  }
  function renderScenes() {
    byId("storiesScenes").innerHTML=scenes.map((s,i)=>`<section class="story-scene" data-scene="${i}"><div class="story-scene-heading"><h3>Scene ${i+1}</h3><button class="btn ghost" type="button" data-remove-scene="${i}">Remove scene ${i+1}</button></div><div class="story-scene-grid"><div class="stories-field"><label for="story-narration-${i}">Narration</label><textarea class="scene-narration" id="story-narration-${i}" data-scene-field="narration" data-index="${i}" rows="5">${esc(s.narration||"")}</textarea></div><div class="stories-field"><label for="story-direction-${i}">Visual direction</label><textarea id="story-direction-${i}" data-scene-field="visual_prompt" data-index="${i}" rows="5">${esc(s.visual_prompt||"")}</textarea></div></div><div class="story-stage-controls">${[{key:"setting",label:"Stage setting",values:["corridor","forest","street","room","station"]},{key:"subject",label:"Subject",values:["figure","creature","none"]},{key:"action",label:"Scene motion",values:["approach","reveal","vanish","follow","wait"]}].map(control=>`<div class="stories-field"><label for="story-${control.key}-${i}">${control.label}</label><select id="story-${control.key}-${i}" data-scene-field="visual_${control.key}" data-index="${i}">${control.values.map(value=>`<option value="${value}" ${(s.visual?.[control.key]||({setting:"corridor",subject:"figure",action:"wait"})[control.key])===value?"selected":""}>${value.charAt(0).toUpperCase()+value.slice(1)}</option>`).join("")}</select></div>`).join("")}</div><p class="story-asset-note">Stage controls direct the original shadow theatre. Visual direction guides any configured image provider.</p>${s.asset_path?'<p class="story-asset-note">This scene has a saved visual asset.</p>':""}</section>`).join("")||'<p class="stories-library-empty">No scenes yet. Add a scene or save a manuscript to build the scene sequence.</p>';
  }
  function renderProject(fill=false) {
    const p=project(); byId("storiesEmpty").hidden=!!p; byId("storiesEditor").hidden=!p;
    if(!p){renderControls();return;}
    byId("storiesEditorHeading").textContent=p.title||"Untitled story";
    byId("storiesProjectStatus").textContent=label(p.status); byId("storiesProjectStatus").className=`stories-status ${p.status||""}`;
    byId("storiesProjectMeta").textContent=`${genreName(p.genre)} · ${p.format==="animated"?"Animated scenes":"Still illustrations"} · ${p.duration_s}s requested${p.voice?` · ${p.voice}`:""}`;
    const job=data?.job?.project_id===p.id?data.job:null, progress=Math.round(Math.min(1,Math.max(0,Number(job?.progress??p.progress)||0))*100);
    byId("storiesJob").hidden=!active(p)&&!p.error; byId("storiesJobStage").textContent=label(job?.stage||p.status);
    byId("storiesJobPercent").textContent=`${progress}%`; byId("storiesJobProgress").value=progress;
    byId("storiesJobDetail").textContent=active(p)?"Your local production engine is working. You can leave this section and return later.":"The last production attempt stopped. Review the message and try again.";
    message("storiesProjectError",p.error||"");
    if(fill&&!edited){
      const pub=publicData(p); byId("storyTitle").value=p.title||""; byId("storyScript").value=p.script||"";
      byId("storyPublicTitle").value=pub.title||""; byId("storyPublicDescription").value=pub.description||"";
      byId("storyPublicTags").value=Array.isArray(pub.tags)?pub.tags.join(", "):(pub.tags||"");
      byId("storyPublicHashtags").value=Array.isArray(pub.hashtags)?pub.hashtags.join(", "):(pub.hashtags||"");
      scenes=structuredClone(p.scenes||[]);renderScenes();
    }
    const review=p.review||{}, issues=Array.isArray(review.issues)?review.issues:[];
    byId("storiesPrivateReview").innerHTML=review.reason||issues.length?`<p>${esc(review.reason||"Review completed.")}</p>${issues.length?`<ul>${issues.map(i=>`<li>${esc(typeof i==="string"?i:JSON.stringify(i))}</li>`).join("")}</ul>`:""}`:'<p>No private review has been saved for this project.</p>';
    const url=p.video_url||p.output?.video_url||(p.status==="ready"&&p.output?.video_path?`/api/stories/projects/${encodeURIComponent(p.id)}/video`:"");
    const safe=url&&url.startsWith(`/api/stories/projects/${encodeURIComponent(p.id)}/`)?url:"";
    byId("storiesPreview").hidden=!safe; if(safe){const video=byId("storiesVideo");if(video.getAttribute("src")!==safe)video.src=safe;byId("storiesDownload").href=safe;}else{byId("storiesVideo").pause();byId("storiesVideo").removeAttribute("src");}
    const posts=p.publishing||p.publish||{};const entries=Object.entries(posts).filter(([,v])=>v&&typeof v==='object');byId("storiesPublishStatus").textContent=entries.length?entries.map(([k,v])=>`${k}: ${v.status||'queued'}${v.error?` · ${v.error}`:''}`).join(' · '):"Ready videos can be sent to your selected connected accounts.";
    renderControls();
  }
  function initOptions() {
    if(!data)return;
    const s=data.settings||{}, caps=data.capabilities||{}, g=byId("storiesGenre");
    const genreOptions=(data.genres||[]).map(v=>`<option value="${esc(v.id)}">${esc(v.label)}</option>`).join("");if(g.innerHTML!==genreOptions){const before=g.value;g.innerHTML=genreOptions;g.value=before||s.default_genre||g.options[0]?.value||"";}
    const voices=caps.voices||[],voice=byId("storiesVoice"),voiceOptions=voices.length?voices.map(v=>`<option value="${esc(v.id)}">${esc(v.label||v.id)}</option>`).join(""):'<option value="">No narrator available</option>';
    if(voice.innerHTML!==voiceOptions){const before=voice.value;voice.innerHTML=voiceOptions;if(voices.some(v=>v.id===(before||s.voice)))voice.value=before||s.voice;}
    if(initialized)return;initialized=true;
    const duration=byId("storiesDuration");duration.min=s.min_duration_s||30;duration.max=s.max_duration_s||900;duration.value=s.default_duration_s||60;byId("storiesLength").value=Number(duration.value)>180?"episode":"short";
    byId("storiesTopic").maxLength=s.max_topic_chars||1200;byId("storyTitle").maxLength=s.max_title_chars||100;byId("storyPublicTitle").maxLength=100;
    const format=document.querySelector(`[name="story_format"][value="${s.default_format==="animated"?"animated":"still"}"]`);if(format)format.checked=true;
  }
  function renderReadiness() {
    const c=data?.capabilities||{};
    byId("storiesReadiness").innerHTML=`<p><strong>Narrator</strong> · ${c.narrator_available?"Available locally":"Not available"}</p><p><strong>Visuals</strong> · ${esc(c.visual_provider?.label||"Checking provider")}</p>${(c.reasons||[]).map(r=>`<p>${esc(r)}</p>`).join("")}`;
    byId("storiesFormatNote").textContent=document.querySelector('[name="story_format"]:checked')?.value==="animated"?(c.animated_available?"Animated scene production is available.":"Animated production needs a configured visual provider."):(c.still_available?"Still illustration production is available.":"Still production needs a configured visual provider.");
    byId("storiesCreateNote").textContent=data?.settings?.auto_render?"The director plans, the writer creates, and the reviewer checks your story. Passing drafts render automatically; publishing follows your Story publishing settings.":"The director plans, the writer creates, and the reviewer checks your story. Render the saved manuscript when it is ready.";
  }
  async function refresh(quiet=false) {
    if(fetching)return;fetching=true;
    try {data=await request("/api/stories");data.projects=data.projects||[];message("storiesGlobalErrorText","");byId("storiesGlobalError").hidden=true;initOptions();renderReadiness();if(!selected&&data.projects.length)selected=data.projects[0].id;if(selected&&!project()){selected=null;edited=false;}renderLibrary();renderProject(!edited);}
    catch(e){if(!quiet||!data){byId("storiesGlobalError").hidden=false;byId("storiesGlobalErrorText").textContent=e.message;} }
    finally{fetching=false;renderControls();}
  }
  async function selectProject(id) {if(edited&&!await ask({title:"Discard unsaved story changes?",body:"Your saved draft stays intact. The changes currently in this editor will be discarded.",ok:"Discard changes",danger:true}))return;selected=id;edited=false;manuscriptChanged=false;renderLibrary();renderProject(true);updateDirty(false);if(innerWidth<980)byId("storiesEditor").scrollIntoView({block:"start",behavior:"instant"});}
  async function save() {
    const p=project();if(!p)return;const split=id=>byId(id).value.split(",").map(x=>x.trim()).filter(Boolean);
    const payload={title:byId("storyTitle").value.trim(),script:byId("storyScript").value,public_copy:{youtube:{title:byId("storyPublicTitle").value.trim(),description:byId("storyPublicDescription").value,tags:split("storyPublicTags"),hashtags:split("storyPublicHashtags")}}};
    if(!manuscriptChanged){payload.scenes=scenes;payload.script=scenes.map(s=>s.narration||"").join("\n\n");}
    sending=true;renderControls();try{const v=projectBody(await request(`/api/stories/projects/${encodeURIComponent(p.id)}`,{method:"PUT",json:payload}));putProject(v);manuscriptChanged=false;updateDirty(false);renderProject(true);renderLibrary();toast("Story changes saved.");}finally{sending=false;renderControls();}
  }
  async function projectAction(action) {
    const p=project();if(!p)return;sending=true;renderControls();
    try{const result=await request(`/api/stories/projects/${encodeURIComponent(p.id)}/${action}`,{method:"POST",json:{}});putProject(projectBody(result));await refresh();}finally{sending=false;renderControls();}
  }
  function setPane(name){document.querySelectorAll('[data-story-pane]').forEach(b=>{const on=b.dataset.storyPane===name;b.setAttribute("aria-selected",String(on));b.tabIndex=on?0:-1;});document.querySelectorAll('.stories-editor-pane').forEach(el=>el.hidden=el.id!==`story-pane-${name}`);}
  function showError(e){toast(e.message||String(e));message("storiesProjectError",e.message||String(e));byId("storiesJob").hidden=false;}
  async function loadPublishing(){
    try{publication=await request("/api/stories/publishing");const cfg=publication.config||publication;const dest=publication.destinations||[];byId("storiesAutoPublish").checked=!!cfg.enabled;byId("storiesPrivacy").value=cfg.privacy||"public";
      byId("storiesDestinations").innerHTML=dest.length?dest.map(d=>`<label class="stories-destination"><input type="checkbox" name="story_destination" value="${esc(d.id||d.platform)}" ${d.ready===false?"disabled":""} ${(cfg.destinations||[]).includes(d.id||d.platform)?"checked":""}><span><b>${esc(d.label||d.id||d.platform)}</b><small>${esc(d.reason||(d.ready===false?"Connect this account in Stories → Accounts.":d.account_label||d.account||"Connected account"))}</small></span></label>`).join(""):'<p>No publishing destinations are configured. Connect an account in Stories → Accounts.</p>';
      message("storiesPublishError","");renderControls();
    }catch(e){message("storiesPublishError",e.message);}
  }
  byId("storiesCreateForm").addEventListener("submit",async e=>{e.preventDefault();if(sending)return;if(edited&&!await ask({title:"Discard unsaved story changes?",body:"Starting a new story will replace the current editor. Save your edits first to keep them.",ok:"Discard and create",danger:true}))return;sending=true;renderControls();message("storiesCreateError","");try{const p=projectBody(await request("/api/stories/projects",{method:"POST",json:{topic:byId("storiesTopic").value.trim(),genre:byId("storiesGenre").value,format:document.querySelector('[name="story_format"]:checked').value,duration_s:Number(byId("storiesDuration").value),voice:byId("storiesVoice").value}}));putProject(p);selected=p.id;edited=false;manuscriptChanged=false;renderLibrary();renderProject(true);await refresh();}catch(err){message("storiesCreateError",err.message);}finally{sending=false;renderControls();}});
  byId("storiesLibrary").addEventListener("click",e=>{const b=e.target.closest('[data-story-id]');if(b)selectProject(b.dataset.storyId);});
  byId("storiesLibrarySearch").addEventListener("input",renderLibrary);
  byId("storiesLength").addEventListener("change",()=>{const input=byId("storiesDuration");input.value=byId("storiesLength").value==="short"?Math.min(60,Number(input.max)):Math.min(480,Number(input.max));});
  document.querySelectorAll('[name="story_format"]').forEach(el=>el.addEventListener("change",renderReadiness));
  byId("storiesEditForm").addEventListener("input",e=>{const f=e.target.dataset.sceneField;if(f){const scene=scenes[Number(e.target.dataset.index)];if(f.startsWith("visual_")){scene.visual={setting:"corridor",subject:"figure",action:"wait",...scene.visual,[f.slice(7)]:e.target.value};}else{scene[f]=e.target.value;}if(f==="narration"){byId("storyScript").value=scenes.map(s=>s.narration||"").join("\n\n");manuscriptChanged=false;}}else if(e.target.id==="storyScript")manuscriptChanged=true;updateDirty();});
  byId("storiesEditForm").addEventListener("submit",e=>{e.preventDefault();save().catch(showError);});
  byId("storiesScenes").addEventListener("click",e=>{const b=e.target.closest('[data-remove-scene]');if(!b)return;scenes.splice(Number(b.dataset.removeScene),1);renderScenes();byId("storyScript").value=scenes.map(s=>s.narration||"").join("\n\n");manuscriptChanged=false;updateDirty();});
  byId("storiesAddScene").addEventListener("click",()=>{scenes.push({id:crypto.randomUUID(),narration:"",visual_prompt:""});renderScenes();updateDirty();byId(`story-narration-${scenes.length-1}`).focus();});
  byId("storiesDiscard").addEventListener("click",async()=>{if(await ask({title:"Discard these changes?",body:"Return this editor to the saved manuscript and scene direction.",ok:"Discard",danger:true})){manuscriptChanged=false;updateDirty(false);renderProject(true);}});
  byId("storiesRender").addEventListener("click",()=>projectAction("render").catch(showError));byId("storiesReview").addEventListener("click",()=>projectAction("review").catch(showError));byId("storiesCancel").addEventListener("click",()=>projectAction("cancel").catch(showError));byId("storiesRetry").addEventListener("click",()=>projectAction("retry").catch(showError));
  byId("storiesDelete").addEventListener("click",async()=>{const p=project();if(!p||!await ask({title:"Delete this story?",body:`“${p.title||"Untitled story"}” and its saved project files will be removed.`,ok:"Delete story",danger:true}))return;try{await request(`/api/stories/projects/${encodeURIComponent(p.id)}`,{method:"DELETE"});selected=null;edited=false;await refresh();}catch(e){showError(e);}});
  byId("storiesCopyPublic").addEventListener("click",async()=>{try{await navigator.clipboard.writeText([byId("storyPublicTitle").value,byId("storyPublicDescription").value,byId("storyPublicHashtags").value].filter(Boolean).join("\n\n"));toast("Public title and description copied.");}catch(_){toast("Copy is unavailable here. Select the public text and copy it manually.");}});
  document.querySelectorAll('[data-story-pane]').forEach(b=>b.addEventListener("click",()=>setPane(b.dataset.storyPane)));
  document.querySelector('.stories-editor-tabs').addEventListener("keydown",e=>{if(!["ArrowLeft","ArrowRight","Home","End"].includes(e.key))return;e.preventDefault();const tabs=[...document.querySelectorAll('[data-story-pane]')],i=tabs.indexOf(document.activeElement);const next=e.key==="Home"?0:e.key==="End"?tabs.length-1:(i+(e.key==="ArrowRight"?1:-1)+tabs.length)%tabs.length;setPane(tabs[next].dataset.storyPane);tabs[next].focus();});
  byId("storiesReload").addEventListener("click",()=>{refresh();loadPublishing();});byId("storiesSettings").addEventListener("click",()=>window.showStorySection("settings"));
  byId("storiesAccounts").addEventListener("click",()=>window.showStorySection("accounts"));
  byId("storiesPublishingForm").addEventListener("submit",async e=>{e.preventDefault();const b=byId("storiesSavePublishing");b.disabled=true;try{await request("/api/stories/publishing",{method:"PUT",json:{enabled:byId("storiesAutoPublish").checked,destinations:selectedDestinations(),privacy:byId("storiesPrivacy").value}});message("storiesPublishError","");publicationEdited=false;toast("Story publishing preferences saved.");await loadPublishing();}catch(err){message("storiesPublishError",err.message);}finally{b.disabled=false;}});
  byId("storiesDestinations").addEventListener("change",renderControls);
  byId("storiesPublishingForm").addEventListener("change",()=>{publicationEdited=true;});
  byId("storiesPublishNow").addEventListener("click",async()=>{const p=project();if(!p)return;sending=true;renderControls();try{await request(`/api/stories/projects/${encodeURIComponent(p.id)}/publish`,{method:"POST",json:{destinations:selectedDestinations()}});toast("Story submitted to the publishing queue.");await refresh();}catch(err){message("storiesPublishError",err.message);}finally{sending=false;renderControls();}});
  window.addEventListener("beforeunload",e=>{if(edited||publicationEdited){e.preventDefault();e.returnValue="";}});
  window.loadStories=()=>{refresh();loadPublishing();};
  window.storyHasUnsavedChanges=()=>edited||publicationEdited;
  document.addEventListener("visibilitychange",()=>{if(!document.hidden&&byId("view-stories").classList.contains("active"))refresh(true);});
  setInterval(()=>{if(!document.hidden&&byId("view-stories").classList.contains("active"))refresh(true);},4000);
  if(byId("view-stories").classList.contains("active"))window.loadStories();
})();
