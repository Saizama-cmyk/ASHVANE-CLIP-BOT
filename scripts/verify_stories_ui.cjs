/* Isolated browser UI contract test. Story API responses are explicit test fixtures;
   this does not generate stories, narrate, render, or send anything to an account. */
const {chromium}=require('C:/Users/wilco/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),path=require('node:path');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage();
 const base=process.env.ASHVANE_UI_PREVIEW||'http://127.0.0.1:8789',out=path.resolve('artifacts/business-ui');fs.mkdirSync(out,{recursive:true});
 const report={fixture:true,checks:[],errors:[],requests:[],layouts:[]};const check=(name,pass,detail)=>{report.checks.push({name,pass:!!pass,detail});console.log((pass?'PASS ':'FAIL ')+name);if(!pass)throw Error(name+' failed');};
 page.on('pageerror',e=>report.errors.push(e.message));
 const story={id:'0123456789abcdef0123456789abcdef',title:'UI fixture: The Third Knock',topic:'An original cabin story',genre:'paranormal',format:'animated',duration_s:60,voice:'fixture',status:'draft',progress:1,script:'The cabin had two doors. The third knock came from beneath the floor.',scenes:[{id:'scene-one',narration:'The cabin had two doors. The third knock came from beneath the floor.',visual_prompt:'A cabin and a floor hatch',visual:{setting:'cabin',subject:'figure',action:'approach'}}],public_copy:{youtube:{title:'The Third Knock',description:'An original fictional horror story.',tags:['horror'],hashtags:['#HorrorStory']}},review:{passed:true,reason:'PRIVATE UI TEST NOTE',issues:[]},output:{}};
 let stories=[],publishing={destinations:[{id:'youtube',label:'YouTube',ready:true,account_label:'UI fixture account'},{id:'tiktok',label:'TikTok',ready:false,reason:'Connect TikTok in Accounts.'}],config:{enabled:true,destinations:['youtube'],privacy:'public'}};
 await page.route('**/api/stories**',async route=>{
   const req=route.request(),u=new URL(req.url()),p=u.pathname,method=req.method();let body={};if(method!=='GET'){try{body=req.postDataJSON()||{};}catch(_){}}
   report.requests.push({path:p,method,body});let result;
   if(p==='/api/stories/accounts')result={accounts:{youtube_client_id:'',youtube_client_secret:'••••••••',instagram_token:'••••••••'},oauth:{youtube:true,tiktok:false},destinations:[{id:'youtube',label:'YouTube',ready:true,account_label:'Stories fixture channel',account_id:'story-channel-123'}],redirects:{youtube:'http://127.0.0.1:8789/oauth/stories/youtube/callback',tiktok:'https://example.test/callback'},app_credentials:{youtube:{configured:true,inherited:true}}};
   else if(p.includes('/api/stories/accounts/'))result={ok:true,opened:false,url:'https://accounts.google.com/fixture'};
   else if(p==='/api/stories')result={projects:stories,busy:false,job:null,genres:[{id:'paranormal',label:'Paranormal'}],capabilities:{narrator_available:true,still_available:true,animated_available:true,render_available:true,voices:[{id:'fixture',label:'UI fixture narrator'}],visual_provider:{id:'shadow',label:'Original shadow theatre',available:true},reasons:[]},settings:{default_genre:'paranormal',default_format:'animated',default_duration_s:60,max_duration_s:900,min_duration_s:30,auto_render:true}};
   else if(p==='/api/stories/publishing'){if(method==='PUT')publishing.config={...publishing.config,...body};result=publishing;}
   else if(p==='/api/stories/projects'&&method==='POST'){stories=[structuredClone(story)];result=stories[0];}
   else if(method==='PUT'){Object.assign(stories[0],body);if(!body.scenes&&body.script)stories[0].scenes=[{id:'scene-one',narration:body.script,visual_prompt:'A cabin and a floor hatch'}];result=stories[0];}
   else if(p.endsWith('/publish'))result={queued:true};
   else if(p.endsWith('/review')){stories[0].review.passed=true;result=stories[0];}
   else result=stories[0]||{};
   await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(result)});
 });
 try{
   const auth=await(await context.request.get(base+'/api/auth/status')).json();
   const response=await context.request.post(base+(auth.setup?'/api/auth/setup':'/api/auth/login'),{headers:{'X-ClipBot':'1'},data:auth.setup?{name:'Preview',password:'preview-only-2026'}:{password:'preview-only-2026'}});if(!response.ok())throw Error('Preview authentication failed '+response.status());
   await page.goto(base+'/#clips',{waitUntil:'networkidle'});
   await page.locator('#businessToggle').click();await page.locator('button[data-business="stories"]').click();await page.waitForTimeout(300);
   check('Portal animates the actual live shell',await page.locator('.story-portal canvas').count()===1&&await page.locator('.shell').evaluate(e=>getComputedStyle(e).transform!=='none'));
   await page.screenshot({path:path.join(out,'portal-fixture.png')});await page.locator('#view-stories.active').waitFor();await page.waitForTimeout(1000);
   check('Portal releases shell and overlay',await page.locator('.story-portal').count()===0&&await page.locator('.shell').evaluate(e=>getComputedStyle(e).transform==='none'));
   check('Stories is a business with its own navigation',await page.locator('#businessCurrent').innerText()==='Hollow'&&await page.locator('#storiesNav').isVisible()&&!(await page.locator('#clipsNav').isVisible()));
   check('Stories has only supported sections',(await page.locator('#storiesNav button').allTextContents()).map(s=>s.trim().slice(2)).join(',').includes('Create'));
   check('Clip capture status is hidden in Stories',!(await page.locator('#pauseBtn').isVisible())&&!(await page.locator('.rail-foot .status').isVisible()));
   check('Empty state directs creation',await page.locator('#storiesEmpty').isVisible());
   await page.locator('button[data-story-section="publishing"]').click();
   check('Story subsection does not trigger portal',await page.locator('.story-portal').count()===0);
   check('Disconnected destination explains itself',await page.locator('[name="story_destination"][value="tiktok"]').isDisabled());
   await page.locator('button[data-story-section="create"]').click();
   await page.locator('#storiesTopic').fill('A guest hears a third knock from underneath the floor.');await page.locator('#storiesCreate').click();await page.locator('#storiesEditor').waitFor({state:'visible'});
   check('New story appears in real editor',await page.locator('#storyTitle').inputValue()===story.title);
   check('Private review is absent from public description',!(await page.locator('#storyPublicDescription').inputValue()).includes('PRIVATE'));
   await page.locator('#storyScript').fill(story.script+' The hatch was locked from the inside.');
   check('Unsaved manuscript blocks rendering',await page.locator('#storiesRender').isDisabled());await page.locator('button[data-story-section="library"]').click();check('Preserved manuscript does not interrupt navigation',await page.locator('#ask[open]').count()===0&&(await page.locator('#storyScript').inputValue()).includes('hatch'));await page.locator('#storiesSave').click();await page.waitForTimeout(200);
   const update=report.requests.findLast(r=>r.method==='PUT'&&r.path.includes('/projects/'));
   check('Manuscript edit lets backend regenerate coherent scenes',update&&!('scenes'in update.body)&&update.body.script.includes('hatch'));
   await page.locator('#story-tab-scenes').click();check('Scene editor changes panes',await page.locator('#story-pane-scenes').isVisible()&&!(await page.locator('#story-pane-manuscript').isVisible()));
   await page.locator('#story-setting-0').selectOption('forest');await page.locator('#story-action-0').selectOption('reveal');await page.locator('#storiesSave').click();await page.waitForTimeout(200);
   const directed=report.requests.findLast(r=>r.method==='PUT'&&r.path.includes('/projects/'));
   check('Stage controls save actual visual direction',directed?.body.scenes?.[0]?.visual?.setting==='forest'&&directed.body.scenes[0].visual.action==='reveal');
   await page.locator('button[data-story-section="publishing"]').click();await page.locator('#storiesAutoPublish').uncheck();await page.locator('#storiesSavePublishing').click();await page.waitForTimeout(200);
   check('Publishing saves only explicit selected account',report.requests.some(r=>r.path==='/api/stories/publishing'&&r.method==='PUT'&&r.body.enabled===false&&r.body.destinations.join(',')==='youtube'));
   await page.locator('button[data-story-section="library"]').click();stories[0].status='ready';await page.evaluate(()=>loadStories());await page.waitForTimeout(250);
   await page.locator('#storiesPublishNow').evaluate(e=>e.click());await page.waitForTimeout(200);
   check('Publish action uses separate Stories endpoint',report.requests.some(r=>r.path.endsWith('/publish')&&r.body.destinations.join(',')==='youtube'));
   await page.locator('button[data-story-section="accounts"]').click();await page.locator('#storyAccountConnections .business-connection').first().waitFor();
   check('Stories displays its actual verified channel',await page.locator('#storyAccountConnections').innerText().then(s=>s.includes('Stories fixture channel')&&s.includes('story-channel-123')));
   check('Stored secrets never populate credential inputs',await page.locator('#story-account-youtube_client_secret').inputValue()===''&&await page.locator('#story-account-instagram_token').inputValue()==='');
   await page.locator('[data-story-oauth="youtube"][data-action="open"]').click();await page.waitForTimeout(150);check('Failed browser opening exposes manual sign-in link',await page.locator('#storyAccountStatus a').count()===1);
   await page.locator('#story-callback-youtube').fill('http://127.0.0.1:8789/oauth/stories/youtube/callback?code=fixture&state=fixture');await page.locator('[data-story-oauth="youtube"][data-action="paste"]').click();await page.waitForTimeout(150);check('Callback completion uses only Stories account API',report.requests.some(r=>r.path==='/api/stories/accounts/youtube/paste'));
   await page.locator('#story-account-youtube_client_id').fill('unsaved-fixture-client');const before=report.requests.length;await page.locator('[data-story-oauth="youtube"][data-action="open"]').click();check('Account actions preserve unsaved credentials',report.requests.length===before&&await page.locator('#story-account-youtube_client_id').inputValue()==='unsaved-fixture-client');await page.locator('#storyAccountReload').click();await page.locator('#askYes').click();await page.waitForTimeout(100);await page.locator('button[data-story-section="settings"]').click();await page.locator('#storySettingsFields input').first().waitFor();check('Story settings contain no Clip capture or account fields',await page.locator('#storySettingsFields [name^="stories."]').count()>0&&await page.locator('#storySettingsFields [name^="capture."]').count()===0);
   await page.evaluate(()=>show('settings'));await page.waitForTimeout(1400);check('Clip settings exclude Stories sections',await page.locator('#sec-stories,#sec-story_accounts').count()===0);
   for(const width of [1440,390,320]){
     await page.setViewportSize({width,height:width<640?844:1000});await page.waitForTimeout(100);
     for(const view of ['stories','story-accounts','story-settings','clips','desk','research','settings','live','growth','system','studio','setup']){
       await page.evaluate(v=>show(v),view);await page.waitForTimeout(1350);
       const dim=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));report.layouts.push({width,view,...dim});
       check(`${view} has no page overflow at ${width}px`,dim.scroll<=dim.width+1,dim);
     }
     await page.evaluate(()=>showStorySection('library'));await page.waitForTimeout(1350);await page.screenshot({path:path.join(out,`stories-fixture-${width}.png`),fullPage:true});
   }
   await page.emulateMedia({reducedMotion:'reduce'});await page.evaluate(()=>show('clips'));await page.waitForTimeout(150);await page.evaluate(()=>show('stories'));await page.waitForTimeout(150);
   check('Reduced motion swaps with no spatial portal',await page.locator('.story-portal').count()===0&&await page.locator('#view-stories.active').count()===1);
   await page.emulateMedia({reducedMotion:'no-preference'});await page.evaluate(()=>{switchBusiness('clips');switchBusiness('stories');switchBusiness('clips');});await page.waitForTimeout(1400);
   check('Rapid navigation cancels cleanly',await page.locator('.story-portal').count()===0&&await page.locator('#view-clips.active').count()===1);
   await page.evaluate(()=>show('live'));await page.waitForTimeout(150);await page.evaluate(()=>showStorySection('accounts'));await page.waitForTimeout(1350);await page.reload({waitUntil:'networkidle'});check('Business and subsection persist after reload',await page.locator('#businessCurrent').innerText()==='Hollow'&&await page.locator('button[data-story-section="accounts"]').getAttribute('aria-selected')==='true');await page.evaluate(()=>switchBusiness('clips'));await page.waitForTimeout(1350);check('Returning to Clips restores its last subsection',await page.locator('#view-live.active').count()===1);
   check('No browser runtime exceptions',report.errors.length===0,report.errors);
 }finally{fs.writeFileSync(path.join(out,'verification.json'),JSON.stringify(report,null,2));await browser.close();}
 console.log(JSON.stringify({checks:report.checks.length,passed:report.checks.filter(c=>c.pass).length,errors:report.errors,report:path.join(out,'verification.json')}));
})().catch(e=>{console.error(e);process.exitCode=1;});
