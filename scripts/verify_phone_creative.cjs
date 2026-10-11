/* Isolated phone transactions. No engine, OAuth provider, upload or real client is contacted. */
const { chromium } = require('C:/Users/wilco/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const base = process.env.ASHVANE_PHONE_PREVIEW || 'http://127.0.0.1:8140';
(async () => {
 const browser = await chromium.launch({headless:true,channel:'chrome'});
 const report = {fixture:true,widths:[],realEnginesContacted:false,physicalDevicesTested:false};
 for (const width of [320,390]) {
  const context = await browser.newContext({viewport:{width,height:844},reducedMotion:'reduce'}), page = await context.newPage();
  const calls=[], mutations=[], errors=[], mediaHeaders=[];
  let businesses = ['clips','stories','music','social'].map((id,i)=>({id,name:['Surge','Hollow','Resonance','Social Studio'][i],enabled:id==='stories'||id==='social',running:id==='stories'||id==='social',busy:false,message:id==='stories'||id==='social'?'Running':'Stopped'}));
  const clientA='a'.repeat(32),clientB='b'.repeat(32),projectId='11111111-1111-4111-8111-111111111111',revisionId='22222222-2222-4222-8222-222222222222';
  let clients=[{id:clientA,name:'QuirkyCMD',description:'Recovered brand fixture',platforms:['instagram','youtube'],rules:'Never claim universal Roblox compatibility. Use fresh footage.',style_notes:{A:'Original silver brand and starfield',C:'Word-pop showcase with fresh footage'},public_handles:{instagram:'https://instagram.com/quirkycmd'},fresh_footage_required:true},{id:clientB,name:'Second client',description:'Independent fixture',platforms:['youtube'],rules:'Second client only',style_notes:{A:'Second client style'},public_handles:{youtube:'https://youtube.com/@fixture-second'},fresh_footage_required:false}];
  let posts=[], generation=null, producer=null;const memories=new Map();let customProfiles=[];let reference=null;
  let project={id:projectId,title:'Fixture session',parameters:{bpm:120,bars:8,beat_style:'trap'},tracks:[],producer_brief:'',busy:false,revisions:[{id:revisionId,status:'completed',title:'Fixture revision',audio_url:`/api/music/reaper/media/${projectId}/${revisionId}`}]};
  const song={id:'fixture-song',title:'Fixture take',style:'Quiet fixture music',lyrics:'Original fixture lyrics',audio_url:'/api/music/media/fixture-song',duration_seconds:60};
  page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>{localStorage.setItem('ashvane.host','http://fixture.test');localStorage.setItem('ashvane.token','fixture-token');});
  await page.route('https://api.github.com/**',route=>route.fulfill({json:{}}));
  await page.route('http://fixture.test/**',async route=>{
    const req=route.request(),path=new URL(req.url()).pathname,method=req.method();
    if(method==='OPTIONS'){await route.fulfill({status:204,headers:{'Access-Control-Allow-Origin':'*','Access-Control-Allow-Headers':'*','Access-Control-Allow-Methods':'*'}});return;}
    const body=req.postData()?(path.endsWith('/references')?null:req.postDataJSON()):null; calls.push({path,method});if(method!=='GET')mutations.push({path,method,body});
    let data={};
    if(path.startsWith('/api/music/media/')||path.startsWith('/api/music/reaper/media/')||path.startsWith('/api/social/assets/')){
      mediaHeaders.push({path,authorization:req.headers().authorization});
      await route.fulfill({contentType:'audio/wav',headers:{'Access-Control-Allow-Origin':'*'},body:Buffer.alloc(64)});return;
    }
    if(path==='/api/businesses')data={businesses};
    else if(path.startsWith('/api/businesses/')){const id=path.split('/').pop();businesses=businesses.map(row=>row.id===id?{...row,enabled:body.enabled,running:body.enabled,busy:!body.enabled&&id==='music',message:body.enabled?'Running':'Stopping · finishing current work'}:row);data={ok:true,businesses};}
    else if(path==='/api/music/status')data={ready:true,busy:false,message:'Fixture engine ready'};
    else if(path==='/api/music/songs')data={songs:[song]};
    else if(path==='/api/music/songs/fixture-song')data=song;
    else if(path==='/api/music/renders')data={renders:[]};
    else if(path==='/api/music/reaper/status')data={ready:true,busy:false,message:'Fixture REAPER ready',projects:[project]};
    else if(path==='/api/music/create'){generation={id:'generation-1',status:'queued',phase:'Fixture queued'};data=generation;}
    else if(path==='/api/music/jobs/generation-1/cancel'){generation={...generation,status:'cancelled',phase:'Fixture cancelled'};data=generation;}
    else if(path==='/api/music/jobs/generation-1')data=generation;
    else if(path==='/api/music/reaper/projects'){project={...project,title:body.title,producer_brief:body.producer_brief,parameters:body};data=project;}
    else if(path===`/api/music/reaper/projects/${projectId}`)data=project;
    else if(path.endsWith('/open'))data={opened:true,message:'Opened on PC'};
    else if(path.endsWith('/export')){project={...project,busy:true};data=project;}
    else if(path===`/api/music/reaper/projects/${projectId}/cancel`){project={...project,busy:false};data=project;}
    else if(path==='/api/music/produce'){producer={id:'producer-1',project_id:body.project_id,status:'queued',phase:'Fixture planning'};data=producer;}
    else if(path==='/api/music/production-jobs/producer-1/cancel'){producer={...producer,status:'cancelled',phase:'Fixture producer cancelled'};data=producer;}
    else if(path==='/api/music/production-jobs/producer-1')data=producer;
    else if(path==='/api/social/clients'&&method==='GET')data={clients};
    else if(path==='/api/social/clients'&&method==='POST'){const client={id:'c'.repeat(32),public_handles:{},...body};clients.push(client);data={ok:true,client};}
    else if(/^\/api\/social\/clients\/[ab]+$/.test(path)&&method==='PATCH'){const id=path.split('/').pop();clients=clients.map(row=>row.id===id?{...row,...body}:row);data={ok:true,client:clients.find(row=>row.id===id)};}
    else if(path.startsWith('/api/creative-memory/')){const key=path+new URL(req.url()).search;if(method==='PUT'){memories.set(key,{guidance:body.guidance,feedback:[],reference_guidance:[]});data={ok:true};}else if(method==='POST')data={ok:true};else data=memories.get(key)||{guidance:'',feedback:[],reference_guidance:[{asset_id:'learned-ref',name:'Brand reference',status:'partial',rules:['Preserve source claims'],summary:'Fixture learned reference'}]};}
    else if(path==='/api/music/lyrics')data={title:'Suggested take',lyrics:'Suggested original lyrics'};
    else if(path==='/api/stories/ideas')data={ideas:[{title:'Original fixture idea',premise:'A radio hears tomorrow',reason:'Original premise'}]};
    else if(path==='/api/stories/projects'&&method==='POST')data={ok:true,project:{id:'story-1'}};
    else if(path.endsWith('/ideas'))data={ideas:[{title:'Command spotlight',hook:'One original command',brief:'Show one real command with fresh footage.',reason:'Client-specific idea'}]};
    else if(path.endsWith('/references')){assert.equal(req.headers().authorization,'Bearer fixture-token');assert.equal(req.headers()['x-style-profile'],'A');reference={id:'uploaded-reference',name:decodeURIComponent(req.headers()['x-filename']),kind:'text',reference:true,historical:false,analysis_status:'partial',analysis_summary:'Fixture text analysis'};data={ok:true,asset:reference};}
    else if(path.endsWith('/style-profiles')&&method==='POST'){const profile={id:'custom-style',client_id:path.split('/')[4],...body};customProfiles.push(profile);data={ok:true,profile};}
    else if(path.endsWith('/style-profiles')){const id=path.split('/')[4];data={profiles:Object.entries(clients.find(c=>c.id===id)?.style_notes||{}).map(([key,instructions])=>({id:key,name:`Style ${key}`,instructions,client_id:id})).concat(customProfiles.filter(p=>p.client_id===id))};}
    else if(path.endsWith('/accounts')&&path.startsWith('/api/social/')){const id=path.split('/')[4];data={public_handles:clients.find(row=>row.id===id).public_handles,publishing_available:false};}
    else if(path.endsWith('/assets')){const id=path.split('/')[4];data={assets:[{id:`asset-${id[0]}`,client_id:id,name:`${id===clientA?'QuirkyCMD':'Second client'} reference`,kind:'audio',historical:true,url:`/api/social/assets/asset-${id[0]}`}]};}
    else if(path.endsWith('/content')&&path.startsWith('/api/social/clients/')){const id=path.split('/')[4];if(method==='GET')data={items:posts.filter(row=>row.client_id===id)};else{const item={id:'d'.repeat(32),client_id:id,...body};posts.push(item);data={ok:true,item};}}
    else if(path.endsWith('/draft')){const id=path.split('/')[4];const item={id:'e'.repeat(32),client_id:id,title:'Fixture social draft',script:'Original fixture script',caption:'Fixture caption',hashtags:['#fixture'],pinned_comment:'Fixture pinned comment',notes:'',style:body.style,platforms:body.platforms,status:'draft',scheduled_at:'',asset_ids:[],requires_fresh_footage:true};posts.push(item);data={ok:true,item};}
    else if(path.startsWith('/api/social/content/')){const id=path.split('/').pop();if(method==='DELETE'){posts=posts.filter(row=>row.id!==id);data={ok:true};}else{posts=posts.map(row=>row.id===id?{...row,...body}:row);data={ok:true,item:posts.find(row=>row.id===id)};}}
    else if(path==='/api/social/calendar')data={items:posts.filter(row=>row.scheduled_at),publishing_available:false};
    else if(path==='/api/settings/schema')data={properties:{music:{$ref:'#/$defs/Music'},social:{$ref:'#/$defs/Social'},capture:{title:'Capture'}},$defs:{Music:{properties:{producer_model:{title:'Music producer model',type:'string'}}},Social:{properties:{model:{title:'Social local model',type:'string'}}}}};
    else if(path==='/api/settings')data={music:{producer_model:'fixture'},social:{model:'fixture'}};
    else if(path==='/api/stories')data={settings:{},genres:[],projects:[{id:'story-fixture',title:'Fixture manuscript',script:'Original story manuscript',status:'draft',genre:'paranormal',format:'still',duration_s:60,scenes:[]}],capabilities:{}};
    else if(path==='/api/stories/publishing')data={config:{},destinations:[]};
    await route.fulfill({contentType:'application/json',headers:{'Access-Control-Allow-Origin':'*'},body:JSON.stringify(data)});
  });
  const tab=async name=>{await page.getByRole('tab',{name,exact:true}).click();};
  const switchTo=async name=>{await page.getByRole('button',{name:new RegExp(`^${name} ·`)}).click();await page.waitForTimeout(250);};
  await page.goto(base);await switchTo('Hollow');
  await page.getByRole('button',{name:'Create story draft',exact:true}).click();await page.getByText('Story production started on your PC. You can leave this screen while it works.',{exact:true}).waitFor();assert.equal(mutations.at(-1).body.topic_mode,'generated');assert.equal(mutations.at(-1).body.topic,'');
  await page.getByRole('radio',{name:'Use my premise',exact:true}).click();await page.getByLabel('Story premise',{exact:true}).fill('Preserved owner premise');await page.getByRole('radio',{name:'Generate a premise',exact:true}).click();await page.getByRole('button',{name:'Suggest story premises',exact:true}).click();await page.getByRole('button',{name:'Use premise 1',exact:true}).click();await page.getByRole('radio',{name:'Use my premise',exact:true}).click();assert.equal(await page.getByLabel('Story premise',{exact:true}).inputValue(),'Preserved owner premise');
  await tab('Library');await page.getByRole('button',{name:/Fixture manuscript/}).click();await page.getByLabel('Narrated manuscript',{exact:true}).fill('Retained edited manuscript');await tab('Create');await page.getByRole('button',{name:'Keep editing',exact:true}).click();assert.equal(await page.getByLabel('Narrated manuscript',{exact:true}).inputValue(),'Retained edited manuscript');await tab('Create');await page.getByRole('switch',{name:"Don't show again",exact:true}).click();await page.getByRole('button',{name:'Leave editor',exact:true}).click();await tab('Library');assert.equal(await page.getByLabel('Narrated manuscript',{exact:true}).inputValue(),'Retained edited manuscript');await tab('Create');await page.getByRole('button',{name:'Keep editing',exact:true}).waitFor({state:'hidden'});assert.equal(await page.evaluate(()=>localStorage.getItem('ashvane.skip-navigation-warning')),'yes');
  await switchTo('Resonance');await page.getByLabel('Musical direction · optional',{exact:true}).waitFor();
  assert(!mutations.some(row=>row.path.startsWith('/api/businesses/')),'Navigation must not start a business');
  assert(await page.getByRole('button',{name:'Generate local take',exact:true}).isDisabled());
  await page.getByRole('button',{name:'Start Resonance',exact:true}).click();await page.getByRole('button',{name:'Stop Resonance',exact:true}).waitFor();
  assert.equal(businesses.find(row=>row.id==='clips').enabled,false);assert.equal(businesses.find(row=>row.id==='stories').enabled,true);
  await page.getByRole('button',{name:'Generate local take',exact:true}).click();await page.getByRole('button',{name:'Cancel current music job',exact:true}).click();const emptyCreate=mutations.find(row=>row.path==='/api/music/create').body;assert.equal(emptyCreate.style,'');assert.equal(emptyCreate.lyrics_mode,'generated');assert(!('generated_lyrics' in emptyCreate));assert(!('instrumental' in emptyCreate));
  await page.getByRole('radio',{name:'Use my lyrics',exact:true}).click();await page.getByLabel('Your lyrics',{exact:true}).fill('Preserved owner lyrics');await page.getByRole('radio',{name:'Generate lyrics',exact:true}).click();await page.getByRole('button',{name:'Suggest lyrics',exact:true}).click();await page.getByLabel('Generated lyrics',{exact:true}).waitFor();await page.getByRole('radio',{name:'Use my lyrics',exact:true}).click();assert.equal(await page.getByLabel('Your lyrics',{exact:true}).inputValue(),'Preserved owner lyrics');await page.getByRole('radio',{name:'Generate lyrics',exact:true}).click();
  await page.getByRole('switch',{name:'Instrumental',exact:true}).click();await page.getByRole('button',{name:'Generate local take',exact:true}).click();await page.getByRole('button',{name:'Cancel current music job',exact:true}).click();const instrumental=mutations.filter(row=>row.path==='/api/music/create').at(-1).body;assert.equal(instrumental.lyrics,'');assert.equal(instrumental.lyrics_mode,'given');
  await page.getByLabel('Take title',{exact:true}).fill('Mobile fixture');await page.getByLabel('Musical direction · optional',{exact:true}).fill('Original quiet instrumental');
  await switchTo('Social Studio');await switchTo('Resonance');assert.equal(await page.getByLabel('Take title',{exact:true}).inputValue(),'Mobile fixture');
  await page.getByRole('button',{name:'Generate local take',exact:true}).click();await page.getByRole('button',{name:'Cancel current music job',exact:true}).click();
  assert.equal(mutations.find(row=>row.path==='/api/music/create').body.duration_seconds,60);
  await tab('Library');await page.getByRole('button',{name:'Audition Fixture take',exact:true}).click();await page.getByRole('button',{name:'Use this source for a session',exact:true}).click();
  await tab('Production');await page.getByLabel('Production notes',{exact:true}).fill('Keep the vocal clear and tighten the drums.');await page.getByRole('button',{name:'Prepare new session',exact:true}).click();
  await page.getByText('Editable session saved on your PC.',{exact:true}).waitFor();
  assert.equal(mutations.find(row=>row.path==='/api/music/reaper/projects').body.song_id,'fixture-song');
  await page.getByRole('button',{name:'Produce from these notes',exact:true}).click();
  await page.getByText('Producer started from your notes. Listen to the resulting revision before using it.',{exact:true}).waitFor();
  await switchTo('Hollow');await switchTo('Resonance');
  await page.getByRole('button',{name:'Cancel current music job',exact:true}).click();
  assert.equal(mutations.find(row=>row.path==='/api/music/produce').body.project_id,projectId);
  await page.getByRole('button',{name:'Open REAPER on PC',exact:true}).click();await page.getByText('REAPER opened on your PC.',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Audition version 1',exact:true}).click();await page.locator('audio:visible').waitFor();
  await page.getByRole('button',{name:'Export current session',exact:true}).click();await page.getByRole('button',{name:'Cancel session export',exact:true}).click();
  await page.getByText('Session cancellation requested.',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Stop Resonance',exact:true}).click();assert(await page.getByRole('button',{name:'Start Resonance',exact:true}).isDisabled());
  const at=calls.length;await page.waitForTimeout(6500);assert(!calls.slice(at).some(row=>row.path==='/api/state'||row.path.startsWith('/api/research')),'Music must not poll Surge');
  await page.screenshot({path:`artifacts/phone-four-music-${width}.png`});
  await switchTo('Social Studio');await page.getByLabel('Client name',{exact:true}).waitFor();
  assert.equal(await page.getByLabel('Client name',{exact:true}).inputValue(),'QuirkyCMD');
  await page.getByLabel('Content rules',{exact:true}).fill('Never claim universal compatibility. Fresh footage always.');await page.getByRole('button',{name:'Save client direction',exact:true}).click();
  await page.getByText('Client direction saved.',{exact:true}).waitFor();assert.match(clients[0].rules,/Fresh footage/);assert.equal(clients[1].rules,'Second client only');
  await tab('Content');await page.getByRole('button',{name:'Suggest post ideas',exact:true}).click();await page.getByRole('button',{name:'Use post idea 1',exact:true}).click();assert.equal(mutations.filter(row=>row.path.endsWith('/ideas')).at(-1).body.brief,'');assert.equal(mutations.at(-1).body.style_profile_id,'A');
  await page.getByRole('button',{name:'Learning & feedback',exact:true}).click();await page.getByLabel('Learning guidance',{exact:true}).fill('Keep the original client voice.');await page.getByRole('button',{name:'Save learning guidance',exact:true}).click();await page.getByText('Your guidance was saved.',{exact:true}).waitFor();await page.getByLabel('What should it learn?',{exact:true}).fill('Keep source claims precise.');await page.getByRole('button',{name:'Liked it',exact:true}).click();await page.getByText('Feedback saved for future work in this scope.',{exact:true}).waitFor();const feedback=mutations.find(row=>row.path==='/api/creative-memory/social/feedback');assert.equal(feedback.body.client_id,clientA);assert.equal(feedback.body.profile_id,'A');
  await page.getByLabel('What should this post do?',{exact:true}).fill('Explain one command with fresh supplied footage.');await page.getByRole('button',{name:'Draft with local AI',exact:true}).click();
  await page.getByLabel('Working title',{exact:true}).waitFor();await page.getByLabel('Working title',{exact:true}).fill('Reviewed mobile draft');
  page.once('dialog',d=>d.dismiss());await page.getByRole('radio',{name:'Second client',exact:true}).click();assert.equal(await page.getByLabel('Working title',{exact:true}).inputValue(),'Reviewed mobile draft');
  await page.getByLabel('Hashtags · comma separated',{exact:true}).fill('#original, #fixture');await page.getByRole('radio',{name:'Scheduled',exact:true}).click();
  await page.getByLabel('Calendar time · include timezone',{exact:true}).fill('2026-10-20T15:00:00-05:00');await page.getByRole('button',{name:'Save post',exact:true}).click();
  await page.getByText('Post saved for manual publishing.',{exact:true}).waitFor();assert.deepEqual(posts[0].hashtags,['#original','#fixture']);
  await tab('Calendar');await page.getByText('Reviewed mobile draft',{exact:true}).waitFor();
  await tab('Assets');const chooser=page.waitForEvent('filechooser');await page.getByRole('button',{name:'Choose reference file',exact:true}).click();await (await chooser).setFiles({name:'brand-reference.txt',mimeType:'text/plain',buffer:Buffer.from('Use precise original claims.')});await page.getByText('Fixture text analysis',{exact:true}).waitFor();assert(reference);await page.getByRole('button',{name:'Preview QuirkyCMD reference',exact:true}).click();await page.locator('audio:visible').waitFor();
  await tab('Profiles');await page.getByRole('button',{name:'New style profile',exact:true}).click();await page.getByLabel('Style profile name',{exact:true}).fill('Original mobile style');await page.getByLabel('Style instructions',{exact:true}).fill('Fresh footage and precise claims.');await page.getByRole('button',{name:'Save style profile',exact:true}).click();await page.getByText('Client style profile saved.',{exact:true}).waitFor();assert.equal(customProfiles[0].client_id,clientA);await page.getByLabel('instagram public profile URL',{exact:true}).fill('https://instagram.com/quirkycmd-fixture');await page.getByRole('button',{name:'Save client public links',exact:true}).click();
  await page.getByText('Public profiles saved for this client.',{exact:true}).waitFor();assert.equal(clients[1].public_handles.youtube,'https://youtube.com/@fixture-second');
  await page.getByRole('radio',{name:'Second client',exact:true}).click();await page.getByLabel('youtube public profile URL',{exact:true}).waitFor();
  await page.waitForTimeout(100);assert.equal(await page.getByLabel('instagram public profile URL',{exact:true}).inputValue(),'');assert.equal(await page.getByLabel('youtube public profile URL',{exact:true}).inputValue(),'https://youtube.com/@fixture-second');
  await page.getByRole('radio',{name:'QuirkyCMD',exact:true}).click();await tab('Content');await page.getByRole('button',{name:'Reviewed mobile draft · scheduled',exact:true}).click();
  page.once('dialog',d=>d.accept());await page.getByRole('button',{name:'Delete saved draft',exact:true}).click();await page.getByText('Saved post deleted.',{exact:true}).waitFor();assert.equal(posts.length,0);
  await tab('Clients');await page.getByRole('button',{name:'New client',exact:true}).click();await page.getByLabel('Client name',{exact:true}).fill('Third mobile client');await page.getByRole('button',{name:'Save client direction',exact:true}).click();await page.getByText('Client direction saved.',{exact:true}).waitFor();assert.equal(clients.length,3);
  await page.screenshot({path:`artifacts/phone-four-social-${width}.png`});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'Horizontal page overflow');
  assert(mediaHeaders.length>=2);assert(mediaHeaders.every(row=>row.authorization==='Bearer fixture-token'),'Preview requires bearer header');
  assert(!mutations.some(row=>/oauth|publish|stories\/accounts|\/api\/settings$/.test(row.path)),'Social never reuses another business credentials or publishes');
  assert.deepEqual(errors,[]);report.widths.push({width,pass:true,mutations:mutations.length,authenticatedMediaRequests:mediaHeaders.length});console.log(`${width}px creative transactions passed`);await context.close();
 }
 await browser.close();fs.writeFileSync('artifacts/phone-creative-verification.json',JSON.stringify(report,null,2));
})().catch(e=>{console.error(e);process.exit(1)});
