"use strict";
/* Profile IDs bind editors and sign-ins; public links never count as credentials. */
(() => {
  const button = document.getElementById('accountProfilesButton');
  const dialog = document.createElement('dialog');
  dialog.className = 'account-profiles';
  dialog.setAttribute('aria-labelledby', 'accountProfilesTitle');
  dialog.innerHTML = '<header><div class="grow"><h2 id="accountProfilesTitle">Account profiles</h2><p id="accountProfilesIntro"></p></div><button class="btn ghost" type="button" id="accountProfilesClose" aria-label="Close account profiles">Close</button></header><div class="account-profile-body"><aside><div id="accountProfilesList" class="account-profile-list" aria-label="Saved account profiles"></div><button class="btn" type="button" id="accountProfilesNew" style="margin-top:12px">New profile</button></aside><div id="accountProfileEditor" class="account-profile-editor"></div></div><p id="accountProfilesStatus" class="account-profile-status" role="status" aria-live="polite"></p>';
  document.body.append(dialog);
  const node = id => document.getElementById(id);
  const names = {clips:'Surge', stories:'Hollow', music:'Resonance'};
  const platforms = [['youtube','YouTube'],['tiktok','TikTok'],['instagram','Instagram'],['facebook','Facebook'],['discord','Discord']];
  const keys = [['youtube_client_id','YouTube client ID',false],['youtube_client_secret','YouTube client secret',true],['tiktok_client_key','TikTok client key',false],['tiktok_client_secret','TikTok client secret',true],['tiktok_redirect_uri','TikTok HTTPS callback',false],['instagram_user_id','Instagram account ID',false],['instagram_token','Instagram access token',true],['facebook_page_id','Facebook Page ID',false],['facebook_page_token','Facebook Page token',true],['discord_webhook','Discord webhook',true]];
  let business='', data=null, selected='', changed=false, working=false;
  const root = () => '/api/account-profiles/'+business;
  const say = (message,error=false) => {node('accountProfilesStatus').textContent=message;node('accountProfilesStatus').classList.toggle('error',error);};
  async function request(path, options={}) {
    const result = await api(path,options);
    if(!result.ok || result.body?.error || result.body?.ok===false) throw new Error(typeof result.body?.detail==='string'?result.body.detail:result.body?.error||'Account profiles could not be updated.');
    return result.body;
  }
  async function action(run) {
    if(working)return;
    working=true;dialog.querySelectorAll('button').forEach(item=>item.disabled=true);
    try {await run();} catch(error) {say(error.message,true);} finally {working=false;dialog.querySelectorAll('button').forEach(item=>item.disabled=false);}
  }
  async function replaceEditor() {
    return !changed || await ask({title:'Replace these profile edits?',navigation:true,body:'The current profile changes have not been saved.',ok:'Replace edits',cancel:'Keep editing'});
  }
  function render() {
    const rows=data?.profiles||[], row=rows.find(item=>item.id===selected);
    node('accountProfilesList').innerHTML=rows.map(item=>'<button type="button" data-account-profile="'+esc(item.id)+'" aria-pressed="'+(item.id===selected)+'"><strong>'+esc(item.name)+'</strong><small>'+(item.id===data.active_profile_id?'Active profile':'Saved profile')+'</small></button>').join('');
    const fields = platforms.map(([id,label])=>'<div class="field"><label for="profile-link-'+id+'">'+label+' public link</label><input id="profile-link-'+id+'" name="profile_link_'+id+'" data-profile-handle="'+id+'" maxlength="2000" autocomplete="off" value="'+esc(row?.public_handles?.[id]||'')+'" placeholder="https://…"></div>').join('');
    const active = row && row.id===data.active_profile_id;
    node('accountProfileEditor').innerHTML='<form id="accountProfileForm"><div class="field"><label for="accountProfileName">Profile name</label><input id="accountProfileName" name="account_profile_name" required maxlength="120" value="'+esc(row?.name||'')+'" placeholder="Channel, brand or artist name"></div><div class="field"><label for="accountProfileDescription">About this profile</label><textarea id="accountProfileDescription" name="account_profile_description" maxlength="4000">'+esc(row?.description||'')+'</textarea></div><details><summary>Public account links</summary><p class="help">These links identify this brand. They do not grant posting access.</p>'+fields+'</details>'+(row&&business!=='music'?'<details><summary>Developer keys and destination credentials</summary><p class="help">Saved securely for this profile. Leave a secret untouched to keep it; clear an edited field to remove it.</p>'+keys.map(([key,label,secret])=>'<div class="field"><label for="profile-key-'+key+'">'+label+'</label><input id="profile-key-'+key+'" data-profile-key="'+key+'" name="profile_key_'+key+'" type="'+(secret?'password':'text')+'" autocomplete="off" spellcheck="false" value="'+(secret?'':esc(row.accounts?.[key]||''))+'" placeholder="'+(secret&&row.accounts?.[key]?'Saved securely':'Not set')+'"></div>').join('')+'</details>':'')+'<div class="profile-actions"><button class="btn primary" type="submit">'+(row?'Save profile':'Create profile')+'</button>'+(row&&!active?'<button class="btn" type="button" id="accountProfileActivate">Use this profile</button>':'')+'</div></form>';
    if(row){
      const connections=document.createElement('section');connections.className='account-profile-connections';
      connections.innerHTML='<h3>'+(active?'This profile’s accounts':'Saved accounts')+'</h3>'+platforms.map(([id,label])=>{
        const state=row.connections?.[id]||{}, oauth=active&&business!=='music'&&['youtube','tiktok'].includes(id);
        return '<div class="account-profile-connection"><h4>'+label+'</h4><p>'+esc(state.account_label||state.reason||(state.ready?'Connected':'Not connected'))+'</p>'+(state.account_id?'<p>'+esc(state.account_id)+'</p>':'')+(oauth?'<div class="row"><button class="btn" type="button" data-profile-oauth="'+id+'" data-operation="open">Connect '+label+'</button><button class="btn ghost" type="button" data-profile-oauth="'+id+'" data-operation="disconnect">Disconnect</button></div><input id="profile-callback-'+id+'" type="url" autocomplete="off" placeholder="Paste callback address if sign-in did not return" aria-label="'+label+' callback address"><button class="btn ghost" type="button" data-profile-oauth="'+id+'" data-operation="paste">Finish connection</button>':'')+'</div>';
      }).join('')+(active&&business!=='music'?'<button class="btn ghost" type="button" id="accountProfileCancelSignin">Cancel unfinished sign-in</button>':'');
      node('accountProfileEditor').append(connections);
    }
    changed=false;
  }
  async function load(preferred=selected) {
    data=await request(root());selected=data.profiles.some(row=>row.id===preferred)?preferred:data.active_profile_id;render();
    window.dispatchEvent(new CustomEvent('accountprofilechange',{detail:{business,profile_id:data.active_profile_id}}));
    say(business==='music'?'Artist profiles save public links and creative guidance. Music distribution is not connected.':data.queue_policy||'Each profile keeps its own publishing connections.');
  }
  button.onclick=async()=>{
    const next=document.body.dataset.business||'clips';
    if(next==='social'){window.showSocialSection?.('clients');return;}
    if(business!==next){if(!await replaceEditor())return;business=next;data=null;selected='';changed=false;}
    node('accountProfilesTitle').textContent=names[business]+' · Account profiles';
    node('accountProfilesIntro').textContent='Keep each '+(business==='music'?'artist':'channel or brand')+' and its accounts together.';
    if(!dialog.open)dialog.showModal();
    if(!data||!changed)await action(()=>load());
  };
  node('accountProfilesClose').onclick=()=>dialog.close();
  node('accountProfilesNew').onclick=async()=>{if(working||!await replaceEditor())return;selected='';render();say('Name the new profile, then create it.');node('accountProfileName').focus();};
  node('accountProfilesList').onclick=async event=>{const target=event.target.closest('[data-account-profile]');if(!target||working||!await replaceEditor())return;selected=target.dataset.accountProfile;render();};
  node('accountProfileEditor').addEventListener('input',event=>{changed=true;if(event.target.dataset.profileKey)event.target.dataset.changed='true';say('Unsaved edits for this profile.');});
  node('accountProfileEditor').addEventListener('submit',event=>{event.preventDefault();action(async()=>{
    const payload={name:node('accountProfileName').value,description:node('accountProfileDescription').value,public_handles:{}};
    dialog.querySelectorAll('[data-profile-handle]').forEach(input=>{if(input.value.trim())payload.public_handles[input.dataset.profileHandle]=input.value.trim();});
    const edited={};dialog.querySelectorAll('[data-profile-key][data-changed]').forEach(input=>edited[input.dataset.profileKey]=input.value);
    if(Object.keys(edited).length)payload.accounts=edited;
    const result=await request(root()+(selected?'/'+selected:''),{method:selected?'PATCH':'POST',json:payload});
    data=result;if(!selected)selected=result.profiles.at(-1).id;render();say('Profile saved on this PC.');
  });});
  node('accountProfileEditor').addEventListener('click',event=>{const activate=event.target.closest('#accountProfileActivate'), cancel=event.target.closest('#accountProfileCancelSignin'), oauth=event.target.closest('[data-profile-oauth]');if(!activate&&!cancel&&!oauth)return;
    action(async()=>{
      if(changed)throw new Error('Save this profile’s edits before changing its connections.');
      if(activate){
        if(dirty||window.storyAccountHasUnsavedChanges?.())throw new Error('Save or reload your account/settings edits before changing profiles.');
        const result=await request(root()+'/'+selected+'/activate',{method:'POST',json:{}});data=result;render();
        window.dispatchEvent(new CustomEvent('accountprofilechange',{detail:{business,profile_id:selected}}));
        await loadSettings();window.loadStories?.();say('Active profile changed. Other profiles’ queued posts stay held.');
      }else if(cancel){await request(root()+'/'+selected+'/cancel-signin',{method:'POST',json:{}});say('Unfinished sign-in cancelled. Existing saved connections remain.');}
      else{
        const platform=oauth.dataset.profileOauth, operation=oauth.dataset.operation;
        if(operation==='disconnect'&&!await ask({title:'Disconnect '+platform+'?',body:'Remove this profile’s saved sign-in. Published videos remain on the channel.',ok:'Disconnect',danger:true}))return;
        const result=await request(root()+'/'+selected+'/'+platform+'/'+operation,{method:'POST',json:operation==='paste'?{url:node('profile-callback-'+platform).value}:{}});
        await load(selected);say(operation==='open'?'Sign-in opened on your PC. Choose this profile’s channel, then reopen Accounts after approval.':'Connection updated for this profile.');
        if(operation==='open'&&result.opened===false&&result.url){const url=new URL(result.url);if(url.protocol==='https:'){const link=document.createElement('a');link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';link.textContent=' Open sign-in';node('accountProfilesStatus').append(link);}}
      }
    });
  });
  async function refreshHeader(){
    const next=document.body.dataset.business||'clips';button.textContent=next==='social'?'Client profiles':'Account profiles';
    if(next==='social')return;
    try{
      const result=await request('/api/account-profiles/'+next);
      if(document.body.dataset.business!==next)return;
      const active=result.profiles.find(row=>row.id===result.active_profile_id);
      button.textContent=active?.name?'Profile · '+active.name:'Account profiles';
      window.dispatchEvent(new CustomEvent('accountprofilechange',{detail:{business:next,profile_id:result.active_profile_id}}));
    }catch(_){/* The authenticated profile picker reports errors when opened. */}
  }
  window.addEventListener('accountprofilechange',event=>{
    if(event.detail?.business!==document.body.dataset.business||!data||business!==event.detail.business)return;
    const active=data.profiles.find(row=>row.id===event.detail.profile_id);
    if(active)button.textContent='Profile · '+active.name;
  });
  new MutationObserver(refreshHeader).observe(document.body,{attributes:true,attributeFilter:['data-business']});
  const start=window.startAshvane;window.startAshvane=function(){start();refreshHeader();};
})();
