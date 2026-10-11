/* Explicit account fixtures; never connects OAuth or publishes real content. */
const {chromium}=require('C:/Users/wilco/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const base=process.env.ASHVANE_PREVIEW_URL||'http://127.0.0.1:8788', report={fixture:true,checks:[],errors:[],layouts:[],realOAuth:false,realPublishing:false};
 const check=(name,value)=>{report.checks.push({name,passed:!!value});assert(value,name);};
 try{
  for(const width of [1440,390,320]){
   const context=await browser.newContext({viewport:{width,height:1000},reducedMotion:'reduce'}),page=await context.newPage();
   page.on('pageerror',error=>report.errors.push(error.message));
   const auth=await(await context.request.get(base+'/api/auth/status')).json();
   assert((await context.request.post(base+(auth.setup?'/api/auth/setup':'/api/auth/login'),{headers:{'X-ClipBot':'1'},data:{name:'Preview',password:'preview-only-2026'}})).ok());
   const states={},calls=[];let blocked=false;
   for(const business of ['clips','stories','music'])states[business]={active_profile_id:'default',profiles:[{id:'default',name:business+' main',description:'Original account profile',public_handles:{},accounts:{youtube_client_id:'fixture-app',youtube_client_secret:'••••••••'},connections:{youtube:{ready:true,reason:'Fixture channel'}}},{id:'b'.repeat(32),name:business+' second',description:'Independent account profile',public_handles:{youtube:'https://youtube.com/@fixture'},accounts:{},connections:{youtube:{ready:false,reason:'Not connected'}}}],queue_policy:'Items remain bound to their original profile.'};
   await page.route('**/api/account-profiles/**',route=>{
    const req=route.request(),parts=new URL(req.url()).pathname.split('/').slice(3),[business,id,platform,operation]=parts,state=states[business],payload=req.method()==='GET'?null:req.postDataJSON();calls.push({business,id,platform,operation,method:req.method(),payload});
    assert.equal(req.headers()['x-clipbot'],req.method()==='GET'?undefined:'1');
    if(req.method()==='GET')return route.fulfill({json:state});
    if(platform==='activate'){if(blocked)return route.fulfill({status:409,json:{detail:'Finish current work before changing profiles'}});state.active_profile_id=id;return route.fulfill({json:state});}
    if(operation)return route.fulfill({json:{ok:true,opened:true}});
    if(req.method()==='PATCH'){Object.assign(state.profiles.find(row=>row.id===id),payload);return route.fulfill({json:state});}
    if(req.method()==='POST'&&!id){state.profiles.push({id:'c'.repeat(32),...payload,connections:{}});return route.fulfill({json:state});}
    return route.fulfill({json:state});
   });
   await page.goto(base+'/#clips/clips',{waitUntil:'networkidle'});
   await page.locator('#accountProfilesButton').click();await page.locator('#accountProfileName').waitFor();
   check(width+' active profile visible',(await page.locator('#accountProfileName').inputValue())==='clips main');
   await page.locator('#accountProfileEditor summary').filter({hasText:'Developer keys'}).click();
   check(width+' saved secret stays out of input',await page.locator('#profile-key-youtube_client_secret').inputValue()==='');
   await page.locator('[data-account-profile="'+ 'b'.repeat(32)+'"]').click();
   check(width+' inactive profile has no connect button',await page.locator('[data-profile-oauth]').count()===0);
   blocked=true;await page.locator('#accountProfileActivate').click();await page.waitForFunction(()=>document.getElementById('accountProfilesStatus').textContent.includes('Finish current'));
   check(width+' busy switch preserves selected editor',await page.locator('#accountProfileName').inputValue()==='clips second');
   blocked=false;await page.locator('#accountProfileActivate').click();await page.waitForFunction(()=>document.getElementById('accountProfilesStatus').textContent.includes('Active profile changed'));
   await page.locator('[data-profile-oauth="youtube"][data-operation="open"]').click();await page.waitForFunction(()=>document.getElementById('accountProfilesStatus').textContent.includes('Sign-in opened'));
   check(width+' sign-in uses explicit profile',calls.some(row=>row.id==='b'.repeat(32)&&row.platform==='youtube'&&row.operation==='open'));
   await page.locator('#accountProfileName').fill('Renamed fixture channel');await page.locator('#accountProfileForm button[type=submit]').click();await page.waitForFunction(()=>document.getElementById('accountProfilesStatus').textContent==='Profile saved on this PC.');
   check(width+' edit remains scoped',calls.some(row=>row.method==='PATCH'&&row.id==='b'.repeat(32)&&row.payload.name==='Renamed fixture channel'));
   await page.locator('#accountProfilesNew').click();await page.locator('#accountProfileName').fill('Third fixture');await page.locator('#accountProfileForm button[type=submit]').click();await page.waitForFunction(()=>document.getElementById('accountProfilesStatus').textContent==='Profile saved on this PC.');
   check(width+' create does not activate profile',states.clips.active_profile_id==='b'.repeat(32));
   await page.screenshot({path:'artifacts/account-profiles-'+width+'.png'});
   const fit=await page.locator('.account-profiles').evaluate(el=>el.scrollWidth<=el.clientWidth+1);check(width+' modal fits',fit);report.layouts.push({width,fit});
   await page.locator('#accountProfilesClose').click();
   await page.locator('#businessToggle').click();await page.locator('[data-business="music"]').click();await page.locator('body[data-business=music]').waitFor();
   await page.locator('#accountProfilesButton').click();await page.waitForFunction(()=>document.getElementById('accountProfilesTitle').textContent.includes('Resonance'));
   check(width+' artist profile has no publishing controls',await page.locator('[data-profile-oauth]').count()===0&&await page.locator('[data-profile-key]').count()===0);
   check(width+' artist distribution limitation visible',(await page.locator('#accountProfilesStatus').textContent()).includes('distribution is not connected'));
   await page.locator('#accountProfilesClose').click();
   await page.locator('#businessToggle').click();await page.locator('[data-business="social"]').click();await page.locator('body[data-business=social]').waitFor();await page.locator('#accountProfilesButton').click();
   check(width+' Social uses its existing client profiles',!await page.locator('.account-profiles').isVisible()&&await page.locator('body').getAttribute('data-business')==='social');
   await context.close();
  }
  check('No script errors',report.errors.length===0);
 }finally{fs.writeFileSync('artifacts/account-profiles-desktop-report.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
