"use strict";

/* Real engine data only. Research scripts remain drafts; this desk never schedules them. */
let researchData = null, researchFetch = null, researchProblem = "", researchSending = false;
const researchSelected = new Set(), researchExpanded = new Set();
let deskNextAction = () => show("setup");
GUIDE.research = "Choose the niche you want to explain and the feeds or sources you trust. The researcher gathers linked evidence; the director chooses an angle; the writer creates the script and platform copy; the judge checks the claims. Scripts stay in Research for your review. Set the local model for each role here and use System to check what this PC can run.";

function safeSourceUrl(value) {
  try { const url = new URL(String(value)); return ["https:", "http:"].includes(url.protocol) ? url.href : ""; }
  catch (_) { return ""; }
}
function setDeskHtml(id, html) {
  const el = document.getElementById(id);
  if (el && el.innerHTML !== html) el.innerHTML = html;
}
function momentDate(value) {
  const numeric = Number(value);
  const date = numeric > 0 ? new Date(numeric * 1000) : new Date(value);
  return Number.isFinite(date.getTime()) ? date.toLocaleDateString([], {month:"short",day:"numeric"}) : "Date unavailable";
}
function stageName(stage) {
  return {queued:"Waiting",qc:"Checking capture",transcribe:"Transcribing",clipability:"Judge watching",edit:"Editing",scheduled:"Ready to review",posted:"Posted",rejected:"Skipped",failed:"Needs attention",directing:"Choosing an angle",writing:"Writing",judging:"Checking evidence",ready:"Draft ready",needs_review:"Needs review",interrupted:"Interrupted"}[stage] || stage || "Waiting";
}
function statusBadge(status) {
  const cls = ["ready","scheduled","complete","posted"].includes(status) ? "ok" : ["failed","rejected","interrupted","needs_review"].includes(status) ? "rejected" : "";
  return `<span class="badge ${cls}">${esc(stageName(status))}</span>`;
}
async function deskSettings(section) {
  show("settings");
  try { await ensureSettings(); openSection(section); }
  catch (_) { toast("Settings could not be loaded. Try again when the engine reconnects."); }
}
function deskClips() {
  const map = new Map();
  for (const clip of [...clipsCache, ...(state?.samples || [])]) map.set(clip.id, clip);
  return [...map.values()].sort((a,b) => Number(b.created_at || 0)-Number(a.created_at || 0));
}
function reviewReason(clip) {
  const verdict = clip.verdict || {}, viewer = verdict.viewer_review || {};
  const final = clip.final_review || verdict.final_review;
  if (final?.passed === false) return final.reason || (final.issues || []).join(" · ") || "The final cut needs attention.";
  if (clip.stage === "rejected" || verdict.passed === false) return viewer.why_skip || verdict.reason || clip.error || "The judge skipped this moment.";
  return viewer.why_watch || verdict.reason || clip.error || "Open the preview to check the hook, context, and payoff.";
}
function openDeskClip(id) {
  const clip = deskClips().find(c => c.id === id);
  if (!clip) { toast("That clip is no longer in the recent library. Open All clips to refresh."); return; }
  if (!state) state = {samples:[]};
  if (!(state.samples || []).some(c => c.id === id)) state.samples = [...(state.samples || []), clip];
  openPreview(id);
}

function renderDesk() {
  if (!state) return;
  renderPublishingBatch();
  const clips = deskClips(), live = state.stages?.live || {};
  const ready = clips.filter(c => c.stage === "scheduled"), issues = clips.filter(c => c.stage === "failed");
  const working = ["queued","qc","transcribe","clipability","edit"];
  const active = working.reduce((total,key) => total + Number(live[key] || 0), 0);
  const platforms = Object.entries(state.scheduler?.platforms || {});
  const connected = platforms.filter(([,p]) => p.configured && p.enabled).length;
  const readyNow = platforms.filter(([,p]) => p.ready_now).length;
  const required = (window.deskSetupState?.items || []).filter(i => i.required && !i.ok);
  const posts = state.posts || [];
  const ideas = researchData?.ideas || [];
  const reviewIdeas = ideas.filter(i => ["ready","needs_review"].includes(i.status));
  $("#deskDate").textContent = new Date().toLocaleDateString([], {weekday:"long",month:"long",day:"numeric"});
  setDeskHtml("deskCounts", `<div class="desk-count"><b>${ready.length}</b><span>cuts to review</span></div><div class="desk-count"><b>${Number(state.backlog?.in_flight ?? active)}</b><span>in production</span></div><div class="desk-count"><b>${reviewIdeas.length}</b><span>original drafts</span></div><div class="desk-count"><b>${connected}</b><span>publishing connections</span></div>`);
  let title, detail, actionLabel;
  if (required.length) {
    title = "Finish setting up your workspace"; detail = `${required.length} required ${required.length === 1 ? "check needs" : "checks need"} attention. Start with ${required[0].label}.`;
    actionLabel = "Finish setup"; deskNextAction = () => show("setup");
  } else if (ready.length) {
    title = `${ready.length} ${ready.length === 1 ? "cut is" : "cuts are"} ready for your eyes`;
    detail = "Watch the whole cut, check the judge’s reasoning, then choose what deserves a post.";
    actionLabel = "Review next cut"; deskNextAction = () => openDeskClip(ready[0].id);
  } else if (issues.length) {
    title = "A cut needs attention"; detail = reviewReason(issues[0]);
    actionLabel = "Inspect the cut"; deskNextAction = () => openDeskClip(issues[0].id);
  } else if (!connected) {
    title = "Give your content somewhere to go"; detail = "Connect a publishing account, then turn it on in Posting. Your schedule and limits apply.";
    actionLabel = "Connect accounts"; deskNextAction = () => deskSettings("accounts");
  } else if (reviewIdeas.length) {
    title = "An original draft is ready to shape"; detail = "Read the script, check its sources, and copy the version for each platform.";
    actionLabel = "Review a draft"; deskNextAction = () => openResearchIdea(reviewIdeas[0].id);
  } else {
    title = "Make the next post worth watching";
    detail = active ? "Your local production queue is moving. Use this time to research an original angle." : "Capture moments from the streams you watch, or build an original post from linked research.";
    actionLabel = "Find an idea"; deskNextAction = () => show("research");
  }
  $("#deskNextTitle").textContent = title; $("#deskNextDetail").textContent = detail;
  $("#deskNext").disabled = false; $("#deskNext").textContent = actionLabel;
  const rejected = clips.filter(c => c.stage === "rejected");
  const reviewList = [...ready, ...issues].slice(0,5);
  const list = reviewList.length ? reviewList : rejected.slice(0,3);
  $("#deskCutsSub").textContent = ready.length ? `${ready.length} ready in the recent library` : rejected.length ? "See why the judge skipped these moments" : "Good moments start in the live queue";
  setDeskHtml("deskCuts", list.length ? list.map(c => {
    const target = c.event?.target || {}, verdict = c.verdict || {};
    return `<article class="desk-cut"><img src="/media/${encodeURIComponent(c.id)}/poster.jpg" width="88" height="112" alt="" loading="lazy" onerror="this.style.visibility='hidden'"><div>${statusBadge(c.stage)}<h3>${esc(verdict.title || target.display_name || "Captured moment")}</h3><p class="desk-cut-meta">${esc(target.display_name || target.login || "Stream")} · ${esc(target.platform || "")} · ${esc(momentDate(c.created_at))}${Number.isFinite(Number(verdict.score)) ? ` · ${Number(verdict.score).toFixed(1)}/10` : ""}</p><p class="desk-cut-reason">${esc(reviewReason(c))}</p></div><button class="btn" type="button" data-desk-clip="${esc(c.id)}">Watch cut</button></article>`;
  }).join("") : `<div class="desk-empty"><h3>No cuts waiting on you</h3><p>${active ? "The queue is checking and editing your recent moments. They appear here when a cut is ready." : "Follow live streams to capture a moment, or start with an original researched post."}</p><button class="btn" type="button" data-desk-go="live">Open live streams</button></div>`);
  setDeskHtml("deskPlatforms", platforms.length ? platforms.map(([name,p]) => {
    const status = !p.enabled ? "Posting is off" : !p.configured ? "Connection needed" : p.error ? "Last post needs attention" : p.busy ? "Uploading" : p.ready_now ? "Ready now" : "Scheduled window or limit";
    const note = p.error || p.reason || (p.configured && p.enabled ? `${p.posted_24h ?? 0}/${p.cap ?? "—"} posted in 24 hours` : p.configured ? "Connected · enable in Posting" : "Connect in Accounts");
    return `<div class="desk-platform"><i class="desk-dot ${p.error ? "error" : p.ready_now ? "ready" : ""}" aria-hidden="true"></i><div><strong>${esc(name)} <span class="dim small">· ${esc(status)}</span></strong><p>${esc(note)}</p></div></div>`;
  }).join("") : '<div class="desk-note">Publishing status is unavailable. Open Settings → Accounts to check your connections.</div>');
  const rows = [["queued","Waiting for a slot"],["qc","Checking capture"],["transcribe","Speech & captions"],["clipability","Judge watching"],["edit","Editing & final review"]];
  setDeskHtml("deskQueue", rows.map(([key,label]) => `<div class="desk-queue-row"><span>${label}</span><b>${Number(live[key] || 0)}</b></div>`).join("") + `<p class="small dim">${Number(state.monitors?.length || 0)} streams watched · ${readyNow} platforms ready now</p>`);
  setDeskHtml("deskSetup", !window.deskSetupState ? "Checking requirements…" : required.length ? `<strong>${required.length} required checks need attention.</strong><br>${esc(required[0].detail || required[0].label)}` : "Required checks passed. Optional connections and tools are listed in Setup.");
  setDeskHtml("deskPosts", posts.length ? posts.slice(0,6).map(p => {
    const url = safeSourceUrl(p.url);
    return `<div class="desk-post"><time>${esc(momentDate(p.posted_at))}</time><span>${esc(p.platform)} · ${esc(p.login || "Clip")}${p.error ? ` · ${esc(p.error)}` : ""}</span>${url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">View post</a>` : statusBadge(p.status === "ok" ? "posted" : "failed")}</div>`;
  }).join("") : '<p class="dim small">Your actual posting results will appear here.</p>');
  setDeskHtml("deskIdeas", reviewIdeas.length ? reviewIdeas.slice(0,3).map(i => `<button class="desk-idea" type="button" data-desk-idea="${esc(i.id)}">${statusBadge(i.status)}<strong>${esc(i.angle || i.topic)}</strong><p>${esc(i.hook || i.judgement?.reason || "Open the script and its linked evidence.")}</p></button>`).join("") : `<div class="desk-note">${researchProblem ? esc(researchProblem) : researchData?.busy ? "The research team is working. Follow its progress in Research." : "Build an original script with a clear angle and sources you can verify."}</div>`);
}

async function loadResearch() {
  if (researchFetch) return researchFetch;
  researchFetch = (async () => {
    try {
      const result = await api("/api/research");
      if (!result.ok) throw new Error(result.status === 401 ? "Unlock your workspace to load research." : result.body?.error || `Research could not be loaded (${result.status}). Refresh sources to try again.`);
      researchData = result.body; researchProblem = "";
      const available = new Set((researchData.sources || []).map(s => s.id));
      for (const id of researchSelected) if (!available.has(id)) researchSelected.delete(id);
    } catch (error) { researchProblem = error.message || "The research engine is unavailable. Try again in a moment."; }
    finally { researchFetch = null; renderResearch(); renderDesk(); }
  })();
  return researchFetch;
}
function sourceLink(source) {
  const url = safeSourceUrl(source.url);
  return url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(source.title || source.url)}</a>` : `<span>${esc(source.title || "Source link unavailable")}</span>`;
}
function researchPostText(platform, copy) {
  if (!copy || typeof copy !== "object") return typeof copy === "string" ? copy : "";
  if (platform === "youtube") return [copy.title,copy.description,(copy.tags || []).map(t => "#"+t).join(" ")].filter(Boolean).join("\n\n");
  if (["tiktok","instagram"].includes(platform)) return [copy.caption,(copy.hashtags || []).map(t => "#"+String(t).replace(/^#/,"")).join(" ")].filter(Boolean).join("\n\n");
  if (platform === "facebook") return [copy.title,copy.description].filter(Boolean).join("\n\n");
  if (platform === "discord") return copy.message || "";
  return Object.values(copy).filter(v => typeof v === "string").join("\n\n");
}
function ideaDetail(idea) {
  const judgement = idea.judgement || {}, sources = idea.sources || [];
  const resolved = sources.length ? sources : (idea.source_ids || []).map(id => (researchData?.sources || []).find(s => s.id === id)).filter(Boolean);
  const sentenceChecks = Array.isArray(judgement.sentence_checks) ? judgement.sentence_checks : [];
  const sentenceEvidence = sentenceChecks.map(check => {
    const parts = String(check.id || "Sentence").split(":"), number = /^\d+$/.test(parts[parts.length-1]) ? Number(parts.pop())+1 : null;
    const label = parts.join(" ") + (number !== null ? ` · sentence ${number}` : "");
    const needsReview = check.supported !== true || (judgement.unsupported_claims || []).some(warning => String(warning).startsWith(`${check.id}:`));
    const linked = (check.source_ids || []).map(id => resolved.find(source => source.id === id)).filter(Boolean);
    const result = needsReview ? "Needs review" : check.kind === "opinion" ? "Opinion / question" : "Judge: supported";
    return `<li data-sentence-check="${esc(check.id || '')}"><div class="sentence-check-head"><strong>${esc(label)}</strong><span class="badge ${needsReview ? 'rejected' : ''}">${esc(result)}</span></div>${check.evidence ? `<blockquote>${esc(check.evidence)}</blockquote>` : ""}${check.reason ? `<p>${esc(check.reason)}</p>` : ""}${linked.length ? `<div class="idea-links">${linked.map(sourceLink).join("")}</div>` : check.kind === "fact" ? '<p class="research-inline-error">No linked source was saved for this factual sentence.</p>' : ""}</li>`;
  }).join("");
  return `${idea.script ? `<section class="idea-block"><div class="idea-block-head"><h4>Spoken script</h4><button class="btn" type="button" data-research-copy="${esc(idea.id)}" data-copy-kind="script">Copy script</button></div><pre>${esc(idea.script)}</pre></section>` : '<p>The script will appear after the writer finishes.</p>'}
    ${Object.entries(idea.posts || {}).filter(([platform,copy]) => researchPostText(platform,copy)).map(([platform,copy]) => `<section class="idea-block"><div class="idea-block-head"><h4>${esc(platform)} copy</h4><button class="btn" type="button" data-research-copy="${esc(idea.id)}" data-copy-kind="${esc(platform)}">Copy</button></div><pre>${esc(researchPostText(platform,copy))}</pre></section>`).join("")}
    <section class="idea-block"><h4>Saved judge notes</h4><p>${esc(judgement.reason || "Waiting for the judge’s review.")}</p>${(judgement.checks || []).length ? `<ul>${judgement.checks.map(check => `<li>${esc(check)}</li>`).join("")}</ul>` : ""}${(judgement.unsupported_claims || []).length ? `<p class="research-inline-error">Evidence warnings to review:</p><ul>${judgement.unsupported_claims.map(claim => `<li>${esc(claim)}</li>`).join("")}</ul>` : ""}</section>
    ${sentenceEvidence ? `<section class="idea-block"><h4>Sentence evidence</h4><p>Saved judge notes and quoted excerpts. Review every warning above before using this draft.</p><ol class="sentence-checks">${sentenceEvidence}</ol></section>` : ""}
    <section class="idea-block"><h4>Evidence & sources</h4><div class="idea-links">${resolved.length ? resolved.map(sourceLink).join("") : '<span class="dim">No linked sources were attached to this draft.</span>'}</div></section>`;
}
function renderResearchSources() {
  const all = researchData?.sources || [], query = $("#researchSearch").value.trim().toLowerCase();
  const sources = all.filter(s => `${s.title || ""} ${s.summary || ""} ${s.source || ""}`.toLowerCase().includes(query));
  $("#researchSourceCount").textContent = `${all.length} saved sources`;
  setDeskHtml("researchSources", sources.length ? sources.map(s => `<article class="research-source"><input type="checkbox" id="source-${esc(s.id)}" value="${esc(s.id)}" ${researchSelected.has(s.id) ? "checked" : ""} aria-label="Use ${esc(s.title || 'this source')} in draft"><div><label for="source-${esc(s.id)}">${esc(s.source || "Linked source")} · <time>${s.published ? esc(momentDate(s.published)) : "Date unavailable"}</time></label>${sourceLink(s)}<p>${esc(s.summary || "Open the source to read the evidence.")}</p></div></article>`).join("") : `<div class="empty"><strong>${query ? "No sources match that search" : researchProblem ? "Sources are unavailable" : "Start your source notebook"}</strong>${query ? "Try another title or topic." : researchProblem ? esc(researchProblem) : "Set your niche in Research settings, then refresh sources. Choose evidence for the next original post."}</div>`);
  $("#researchSelection").textContent = researchSelected.size ? `${researchSelected.size} selected ${researchSelected.size === 1 ? "source" : "sources"} will guide this draft.` : "Select sources from the notebook, or use the latest research.";
}
function renderResearchIdeas() {
  const ideas = researchData?.ideas || [];
  $("#researchIdeaCount").textContent = `${ideas.length} saved`;
  setDeskHtml("researchIdeas", ideas.length ? ideas.map(i => {
    const warnings = i.judgement?.unsupported_claims || [];
    const note = i.error || (i.status === "needs_review" && warnings.length ? `${warnings.length} evidence ${warnings.length === 1 ? "warning needs" : "warnings need"} attention. Open the saved script, flagged wording, and quoted sources below.` : i.judgement?.reason) || (i.status === "ready" ? "Script and copy reviewed. Read the sources before you use it." : ["needs_review","failed","interrupted"].includes(i.status) ? "Read the judge’s notes before using this draft." : "The team is building this draft. Its output will appear here.");
    return `<article class="research-idea"><div class="idea-top">${statusBadge(i.status)}<time>${esc(momentDate(i.created_at))}</time><button class="btn ghost idea-delete" type="button" data-research-delete="${esc(i.id)}">Delete</button></div><h3>${esc(i.angle || i.topic)}</h3>${i.hook ? `<p class="idea-hook">${esc(i.hook)}</p>` : ""}<div class="idea-judgement"><strong>${i.status === "ready" ? "Reviewed draft" : stageName(i.status)}</strong><p>${esc(note)}</p></div><details data-research-detail="${esc(i.id)}" ${researchExpanded.has(i.id) ? "open" : ""}><summary>Read script, platform copy &amp; sources</summary>${ideaDetail(i)}</details></article>`;
  }).join("") : '<div class="empty"><strong>Your first original draft starts above</strong>Choose a useful topic and let the team develop an angle, a script, and platform copy.</div>');
}
function renderResearch() {
  const busy = Boolean(researchData?.busy || researchSending), agents = researchData?.agents || [];
  const labels = {researcher:"Researcher",director:"Director",scriptwriter:"Writer",judge:"Judge"};
  const status = researchData?.status || "idle";
  $("#researchStatus").textContent = researchProblem ? "Research needs attention" : busy ? `Team working · ${stageName(status)}` : status === "failed" ? "Research needs attention" : "Your source notebook & drafts";
  $("#researchUpdated").textContent = researchData?.updated ? `Research updated: ${momentDate(researchData.updated)} · ${clock(Number(researchData.updated))}. Sources are saved locally.` : "Sources and drafts are kept on this PC. Refresh to begin.";
  const errors = [researchProblem,...(researchData?.errors || [])].filter(Boolean);
  $("#researchErrors").hidden = !errors.length;
  setDeskHtml("researchErrors", errors.map(error => `<p>${esc(error)}</p>`).join(""));
  setDeskHtml("researchAgents", Object.entries(labels).map(([role,label]) => {
    const agent = agents.find(a => a.role === role) || {};
    return `<div class="agent-step ${agent.status === "running" ? "running" : ""}"><div class="agent-top"><strong>${label}</strong><span class="badge">${esc(agent.status || "idle")}</span></div><span class="agent-model" title="${esc(agent.model || '')}">${esc(agent.model || "Model not reported")}</span><p>${esc(agent.detail || "Waiting for a research task.")}</p></div>`;
  }).join(""));
  $("#researchRefresh").disabled = busy; $("#researchRefresh").textContent = busy ? "Team working…" : "Refresh sources";
  $("#researchDraft").disabled = busy; $("#researchDraft").textContent = busy ? "Team working…" : "Draft script & posts";
  $("#researchDraftForm").setAttribute("aria-busy", String(busy));
  renderResearchSources(); renderResearchIdeas();
}
async function researchAction(path, json) {
  researchSending = true; renderResearch();
  try {
    const result = await api(path, {method:"POST", ...(json ? {json} : {})});
    if (!result.ok || result.body?.ok === false) throw new Error(result.body?.error || result.body?.detail || (result.status === 409 ? "The team is already working. Wait for it to finish, then try this topic again." : "The task could not start. Check the research settings and try again."));
    if (json) { $("#researchTopic").value = ""; toast("Draft started. Follow the team’s progress here."); }
    else toast("Research started. Existing sources stay available while it runs.");
    $("#researchFormError").hidden = true;
    if (result.body?.id) researchExpanded.add(result.body.id);
  } catch (error) {
    $("#researchFormError").textContent = error.message;
    $("#researchFormError").hidden = false;
    toast(error.message);
  } finally { researchSending = false; await loadResearch(); }
}
function openResearchIdea(id) {
  researchExpanded.add(id); show("research"); renderResearchIdeas();
  requestAnimationFrame(() => document.querySelector(`[data-research-detail="${CSS.escape(id)}"]`)?.scrollIntoView({block:"center",behavior:matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth"}));
}
async function copyResearchText(text) {
  try { await navigator.clipboard.writeText(text); toast("Copied. The draft is still saved here."); }
  catch (_) { toast("Clipboard access is unavailable. Select and copy the displayed text."); }
}

/* Keep the actual cut in the workspace; the detail dialog retains all posting controls. */
let selectedLibraryId = null;
function selectLibraryClip(id) {
  const clip = clipsCache.find(c => c.id === id);
  const video = $("#libraryVideo");
  const changed = selectedLibraryId !== (clip?.id || null);
  selectedLibraryId = clip?.id || null;
  $$("#gallery .card").forEach(card => {
    const selected = card.dataset.id === selectedLibraryId;
    card.classList.toggle("selected", selected);
    card.setAttribute("aria-pressed", String(selected));
  });
  $("#libraryDetails").disabled = !clip;
  $("#libraryStudio").disabled = !clip;
  video.hidden = !clip;
  $("#libraryEmpty").hidden = !!clip;
  if (changed) {
    video.pause();
    $("#libraryMediaError").hidden = true;
    if (clip) {
      video.poster = `/media/${encodeURIComponent(clip.id)}/poster.jpg`;
      video.src = `/media/${encodeURIComponent(clip.id)}`;
    } else {
      video.removeAttribute("src");
      video.removeAttribute("poster");
      video.load();
    }
  }
  $("#librarySource").textContent = clip ? `${clip.event?.target?.display_name || "Stream clip"} · ${momentDate(clip.created_at)}` : "No clip selected";
  $("#libraryStage").innerHTML = clip ? statusBadge(clip.stage) : "";
  $("#libraryTitle").textContent = clip?.verdict?.title || clip?.event?.target?.display_name || "The next good moment starts here.";
  $("#libraryReason").textContent = clip ? reviewReason(clip) : "Select a clip from the source bin to watch it and inspect the review.";
}
$("#libraryVideo").addEventListener("error", () => {
  if (!selectedLibraryId) return;
  $("#libraryMediaError").textContent = "This video is unavailable or still being prepared. Open the review for its status, or restore the missing file.";
  $("#libraryMediaError").hidden = false;
});
$("#libraryDetails").addEventListener("click", () => {
  $("#libraryVideo").pause();
  if (selectedLibraryId) openDeskClip(selectedLibraryId);
});
$("#libraryStudio").addEventListener("click", () => {
  $("#libraryVideo").pause();
  if (!selectedLibraryId) return;
  openDeskClip(selectedLibraryId);
  $("#pvStudio").click();
});

/* Clip judgement: show what was actually observed, including the final rendered cut. */
const openPreviewBeforeDesk = openPreview;
openPreview = function(id) {
  openPreviewBeforeDesk(id);
  const clip = deskClips().find(c => c.id === id); if (!clip) return;
  $("#pvStudio").onclick = async () => {
    $("#preview").close();
    try {
      await show("studio");
      const button = document.querySelector(`#stList [data-id="${CSS.escape(id)}"]`);
      if (button) button.click(); else toast("This cut is not in the current Studio library. Choose a clip from the list.");
    } catch (_) { toast("Studio could not load this cut. Try again when the engine reconnects."); }
  };
  const verdict = clip.verdict || {}, review = verdict.viewer_review || {}, final = clip.final_review || verdict.final_review;
  const rejected = verdict.passed === false || clip.stage === "rejected" || final?.passed === false;
  const evidence = Array.isArray(review.evidence) ? review.evidence : [];
  const value = v => typeof v === "object" ? JSON.stringify(v) : String(v ?? "");
  const dimensions = [["Hook",review.hook],["Context",review.context],["Payoff",review.payoff],["Pacing",review.pacing]].filter(([,v]) => v !== undefined && v !== "");
  $("#pvReview").innerHTML = `<h3>A viewer’s verdict</h3><p class="review-decision ${rejected ? "rejected" : ""}">${esc(reviewReason(clip))}</p>${dimensions.length ? `<div class="review-dimensions">${dimensions.map(([label,v]) => `<div class="review-dimension"><b>${label}</b><p>${esc(value(v))}</p></div>`).join("")}</div>` : '<p>Detailed viewer notes were not saved for this older cut. The original verdict is listed below.</p>'}${review.confidence !== undefined ? `<p>Judge confidence: ${esc(value(review.confidence))}</p>` : ""}${evidence.length ? `<h4>Moments behind the decision</h4><ol class="review-evidence">${evidence.map(e => `<li><time>${esc(e.at ?? "")}s</time>${esc(e.detail || e.description || "")}</li>`).join("")}</ol>` : ""}${(review.flags || []).length ? `<p class="review-flags">${esc(review.flags.join(" · "))}</p>` : ""}${final ? `<div class="review-final"><strong>Final cut: ${final.passed ? "passed" : "needs attention"}</strong><p>${esc(final.reason || "Final rendered cut was checked.")}</p>${Object.keys(final.checks || {}).length ? `<ul>${Object.entries(final.checks).map(([key,v]) => `<li>${esc(key.replace(/_/g," "))}: ${esc(value(v))}</li>`).join("")}</ul>` : ""}${(final.issues || []).length ? `<p class="review-flags">${esc(final.issues.join(" · "))}</p>` : ""}${(final.evidence || []).length ? `<ol class="review-evidence">${final.evidence.map(e => typeof e === "object" ? `<li><time>${esc(e.at ?? "")}s</time>${esc(e.detail || e.description || "")}</li>` : `<li>${esc(e)}</li>`).join("")}</ol>` : ""}</div>` : '<p class="small dim">No final-cut review has been saved yet.</p>'}`;
  const copyHandler = $("#pvCopy").onclick;
  $("#pvCopy").onclick = event => Promise.resolve(copyHandler?.(event)).catch(() => toast("Clipboard access is unavailable. Copy the text from the clip details."));
};
const renderGalleryBeforeDesk = renderGallery;
renderGallery = function() {
  renderGalleryBeforeDesk();
  renderPublishingBatch();
  $$("#gallery .card").forEach(card => {
    const clip = clipsCache.find(c => c.id === card.dataset.id); if (!clip) return;
    const reason = document.createElement("span"); reason.className = "clip-reason"; reason.textContent = reviewReason(clip); card.querySelector(".meta").append(reason);
    card.setAttribute("role","button"); card.setAttribute("aria-label",`Select ${clip.verdict?.title || clip.event?.target?.display_name || "clip"}. ${stageName(clip.stage)}`);
  });
  const visibleIds = $$("#gallery .card").map(card => card.dataset.id);
  $("#libraryCount").textContent = `${visibleIds.length} ${visibleIds.length === 1 ? "clip" : "clips"}${clipFilter !== "all" ? " shown" : " in library"}`;
  const firstReady = visibleIds.find(id => clipsCache.find(c => c.id === id)?.stage === "scheduled");
  selectLibraryClip(visibleIds.includes(selectedLibraryId) ? selectedLibraryId : firstReady || visibleIds[0] || null);
};

/* Publish the current scheduled queue once. Polling reads progress only. */
let publishingBatch = null, publishingBatchSending = false, publishingBatchReading = false;
let publishingBatchError = "", publishingBatchStartError = "", publishingBatchLastCheck = 0;
function scheduledClipCount() {
  const count = publishingBatch?.scheduled_count;
  return Number.isFinite(Number(count)) && count !== undefined ? Number(count) : clipsCache.filter(c => c.stage === "scheduled").length;
}
function renderPublishingBatch() {
  const button = $("#publishBatchStart"), running = publishingBatch?.status === "running";
  const count = scheduledClipCount();
  const platforms = Object.entries(state?.scheduler?.platforms || {}).filter(([,p]) => p.enabled && p.configured).map(([name]) => name);
  button.disabled = publishingBatchSending || running || !state || count === 0 || platforms.length === 0;
  button.textContent = publishingBatchSending ? "Starting publishing…" : running ? "Publishing scheduled clips…" : "Publish all scheduled now";
  button.setAttribute("aria-busy", String(publishingBatchSending || running));
  $("#publishBatchHint").textContent = running ? `Publishing this batch to ${(publishingBatch.platforms || []).join(", ")}.` : !state ? "Checking the scheduled queue…" : !platforms.length ? "Connect and enable a publishing platform in Settings to post." : count ? `${count} scheduled ${count === 1 ? "clip" : "clips"} · ${platforms.join(", ")}` : "No scheduled clips. New accepted cuts will appear here.";
  const visible = publishingBatchSending || running || Boolean(publishingBatch?.job_id || publishingBatchError || publishingBatchStartError);
  $("#publishBatchPanel").hidden = !visible;
  $("#publishBatchPanel").setAttribute("aria-busy", String(publishingBatchSending || running));
  const job = publishingBatch || {}, total = Number(job.total || 0), done = Number(job.completed || 0);
  const summary = `${Number(job.posted || 0)} posted · ${Number(job.held || 0)} held for review · ${Number(job.failed || 0)} failed`;
  $("#publishBatchStatus").textContent = publishingBatchSending ? "Starting your scheduled queue…" : running ? `${done} of ${total} clips processed. ${summary}${job.current_id ? ` · Checking or uploading ${job.current_id}` : ""}` : job.interrupted ? `Publishing interrupted. ${done} of ${total} processed. ${summary}` : job.status === "complete" ? `Finished ${done} of ${total} clips. ${summary}` : "Publishing needs attention.";
  const error = publishingBatchStartError || publishingBatchError || job.error || "";
  $("#publishBatchError").hidden = !error; $("#publishBatchError").textContent = error;
  const progress = $("#publishBatchProgress"); progress.hidden = !(running || job.job_id); progress.max = Math.max(1,total); progress.value = done;
  const results = Array.isArray(job.results) ? job.results : [];
  $("#publishBatchDetails").hidden = results.length === 0;
  setDeskHtml("publishBatchResults", results.map(result => {
    const clip = clipsCache.find(c => c.id === result.clip_id), title = clip?.verdict?.title || result.clip_id;
    const posts = Object.entries(result.results || {});
    return `<article class="publish-result"><strong>${esc(title)}</strong>${result.error ? `<p class="research-inline-error">${esc(result.error)}</p>` : ""}${posts.map(([platform,post]) => {
      const url = safeSourceUrl(post.url);
      return `<p><b>${esc(platform)}</b> · ${post.ok ? post.already_posted ? "Already posted" : "Posted" : "Failed"}${post.error ? ` · ${esc(post.error)}` : ""}${post.ok && url ? ` · <a href="${esc(url)}" target="_blank" rel="noopener noreferrer">View post</a>` : ""}</p>`;
    }).join("")}</article>`;
  }).join(""));
}
async function readPublishingBatch() {
  if (publishingBatchReading || publishingBatchSending || $("#lock").classList.contains("show")) return;
  publishingBatchReading = true; publishingBatchLastCheck = Date.now();
  try {
    const response = await api("/api/publishing/batch");
    if (!response.ok || !response.body) throw new Error(response.body?.error || response.body?.detail || "Publishing progress could not be loaded. Reconnect to Ashvane to check its status.");
    const finished = publishingBatch?.status === "running" && response.body.status !== "running";
    publishingBatch = response.body; publishingBatchError = "";
    if (publishingBatch.status === "running") publishingBatchStartError = "";
    if (finished) { await loadClips(); renderDesk(); }
  } catch (error) { publishingBatchError = error.message || "Publishing progress is unavailable. The engine may still be posting; reconnect to check."; }
  finally { publishingBatchReading = false; renderPublishingBatch(); }
}
$("#publishBatchStart").addEventListener("click", async () => {
  if (publishingBatchSending || publishingBatch?.status === "running") return;
  publishingBatchSending = true; publishingBatchError = ""; publishingBatchStartError = ""; renderPublishingBatch();
  try {
    const response = await api("/api/publishing/batch", {method:"POST"});
    if (!response.ok || response.body?.ok === false || !response.body) throw new Error(response.body?.error || response.body?.detail || "Publishing could not start. Check your connections and try again.");
    publishingBatch = response.body; $("#publishBatchDetails").open = true;
  } catch (error) { publishingBatchStartError = error.message || "Publishing could not start."; }
  finally { publishingBatchSending = false; renderPublishingBatch(); await readPublishingBatch(); }
});
const showBeforePublishingBatch = show;
show = function(view) {
  if (view !== "clips") $("#libraryVideo").pause();
  if (view !== "studio") $("#stVideo").pause();
  const result = showBeforePublishingBatch(view);
  if (view === "clips") { renderPublishingBatch(); readPublishingBatch(); }
  return result;
};
setInterval(() => {
  if (document.hidden || $("#lock").classList.contains("show")) return;
  if (publishingBatch?.status === "running" || ($("#view-clips").classList.contains("active") && Date.now()-publishingBatchLastCheck > 15000)) readPublishingBatch();
}, 1500);

$("#deskNext").addEventListener("click", () => deskNextAction());
$("#view-desk").addEventListener("click", event => {
  const clip = event.target.closest("[data-desk-clip]"), go = event.target.closest("[data-desk-go]"), field = event.target.closest("[data-desk-field]"), idea = event.target.closest("[data-desk-idea]");
  if (clip) openDeskClip(clip.dataset.deskClip);
  else if (go) show(go.dataset.deskGo);
  else if (field) deskSettings(field.dataset.deskField);
  else if (idea) openResearchIdea(idea.dataset.deskIdea);
});
$("#researchSearch").addEventListener("input", renderResearchSources);
$("#researchSources").addEventListener("change", event => {
  if (!event.target.matches("input[type=checkbox]")) return;
  if (event.target.checked) researchSelected.add(event.target.value); else researchSelected.delete(event.target.value);
  $("#researchSelection").textContent = researchSelected.size ? `${researchSelected.size} selected ${researchSelected.size === 1 ? "source" : "sources"} will guide this draft.` : "Select sources from the notebook, or use the latest research.";
});
$("#researchSettings").addEventListener("click", () => deskSettings("research"));
$("#researchRefresh").addEventListener("click", () => researchAction("/api/research/refresh"));
$("#researchDraftForm").addEventListener("submit", event => {
  event.preventDefault(); if (researchSending || researchData?.busy) return;
  const topic = $("#researchTopic").value.trim();
  if (!topic) { $("#researchFormError").textContent = "Add a topic or question to give the writer a direction."; $("#researchFormError").hidden = false; $("#researchTopic").focus(); return; }
  researchAction("/api/research/draft", {topic,source_ids:[...researchSelected]});
});
$("#researchIdeas").addEventListener("toggle", event => {
  const el = event.target;
  if (!el.matches("details[data-research-detail]")) return;
  if (el.open) researchExpanded.add(el.dataset.researchDetail); else researchExpanded.delete(el.dataset.researchDetail);
}, true);
$("#researchIdeas").addEventListener("click", async event => {
  const copy = event.target.closest("[data-research-copy]"), remove = event.target.closest("[data-research-delete]");
  if (copy) {
    const idea = (researchData?.ideas || []).find(i => i.id === copy.dataset.researchCopy); if (!idea) return;
    await copyResearchText(copy.dataset.copyKind === "script" ? idea.script : researchPostText(copy.dataset.copyKind,idea.posts?.[copy.dataset.copyKind]));
  } else if (remove) {
    if (!await ask({title:"Delete this research draft?",body:"The saved script and platform copy will be removed. Your sources and clips stay in the workspace.",ok:"Delete draft",danger:true})) return;
    remove.disabled = true; remove.textContent = "Deleting…";
    try {
      const result = await api(`/api/research/ideas/${encodeURIComponent(remove.dataset.researchDelete)}`, {method:"DELETE"});
      if (!result.ok) throw new Error(result.body?.error || "The draft could not be deleted.");
      researchExpanded.delete(remove.dataset.researchDelete); toast("Draft deleted."); await loadResearch();
    } catch (error) { toast(error.message); remove.disabled = false; remove.textContent = "Delete"; }
  }
});
window.addEventListener("hashchange", () => { const view = location.hash.slice(1); if (PAGES[view]) show(view); });
window.addEventListener("beforeunload", event => { if ($("#researchTopic").value.trim()) { event.preventDefault(); event.returnValue = ""; } });

/* Keep auxiliary data fresh without adding requests to the fast live-state poll. */
let researchLastCheck = 0, clipsLastCheck = 0, deskReadBusy = false;
async function refreshDeskData() {
  if (document.hidden || $("#lock").classList.contains("show") || deskReadBusy) return;
  const visible = $("#view-desk").classList.contains("active") || $("#view-research").classList.contains("active");
  if (!visible) return;
  deskReadBusy = true;
  try {
    const now = Date.now(), jobs = [];
    if (now-researchLastCheck > (researchData?.busy ? 4000 : 20000)) { researchLastCheck = now; jobs.push(loadResearch()); }
    if ($("#view-desk").classList.contains("active") && now-clipsLastCheck > 20000) { clipsLastCheck = now; jobs.push(loadClips().then(renderDesk)); }
    await Promise.allSettled(jobs);
  } finally { deskReadBusy = false; }
}
renderResearch();
window.startAshvane();
setInterval(refreshDeskData, 4000);
document.addEventListener("visibilitychange", refreshDeskData);
setTimeout(refreshDeskData, 1000);
