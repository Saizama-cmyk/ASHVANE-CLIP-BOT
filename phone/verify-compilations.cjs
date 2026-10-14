/* Isolated Hollow compilation transactions; no production render or publication. */
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const {chromium}=require('C:/Users/wilco/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root=path.resolve(__dirname,'..'),build=path.join(root,'artifacts/phone-interstellar-export');
const types={'.html':'text/html','.js':'text/javascript','.ttf':'font/ttf','.png':'image/png'};
const server=http.createServer((req,res)=>{const name=decodeURIComponent(new URL(req.url,'http://localhost').pathname).replace(/^\/+/,''),target=path.resolve(build,name||'index.html');if(!target.startsWith(build+path.sep)){res.writeHead(403);res.end();return;}fs.readFile(target,(error,bytes)=>{res.writeHead(error?404:200,{'Content-Type':types[path.extname(target)]||'application/octet-stream'});res.end(error?'Missing fixture export':bytes);});});
(async()=>{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const browser=await chromium.launch({headless:true,channel:'chrome'});
 const report={fixture:true,realRendering:false,publication:false,widths:[]};
 try{for(const width of [320,390]){
  const context=await browser.newContext({viewport:{width,height:844},reducedMotion:'reduce'}),page=await context.newPage(),mutations=[],errors=[],media=[];
  let profile='profile-a',busy=false,rejectFirst=true,compilation;
  const finished=(id,title,account='profile-a')=>({id,title,account_profile_id:account,status:'ready',kind:'story',format:'still',genre:'paranormal',duration_s:60,script:'Original fixture manuscript',scenes:[],review:{passed:true,reason:'Fixture source approval'},output:{video_path:'video.mp4'},video_url:`/api/stories/projects/${id}/video`,public_copy:{youtube:{title,description:'Original fiction'}}});
  const projects=[finished('a1','Old House'),finished('a2','Night Radio'),finished('a3','Empty Station'),finished('b1','Other Account Woods','profile-b'),finished('b2','Other Account Lake','profile-b'),{...finished('reject','Rejected Story'),review:{passed:false}},{...finished('draft','Unfinished Story'),status:'draft'}];
  const assembled=()=>{busy=false;Object.assign(compilation,{status:'ready',progress:1,updated_at:Date.now()/1000,output:{video_path:'collection.mp4'},video_url:'/api/stories/projects/collection/video',review:{passed:true,scope:'source_approvals_and_assembly',reason:'Fixture source approvals and technical assembly passed'},compilation:{...compilation.compilation,chapters:[{kind:'opening',title:'Mobile collection',start_s:0,end_s:2.5},{kind:'story',title:'Empty Station',project_id:'a3',start_s:2.5,end_s:64.25},{kind:'story',title:'Old House',project_id:'a1',start_s:64.25,end_s:126.75}]}});};
  page.on('pageerror',error=>errors.push(error.message));
  await page.addInitScript(()=>{localStorage.setItem('ashvane.host','http://fixture.test');localStorage.setItem('ashvane.token','fixture-token');});
  await page.route('https://api.github.com/**',route=>route.fulfill({json:{}}));
  await page.route('http://fixture.test/**',async route=>{
   const req=route.request(),pathname=new URL(req.url()).pathname,method=req.method();
   if(method==='OPTIONS'){await route.fulfill({status:204,headers:{'Access-Control-Allow-Origin':'*','Access-Control-Allow-Headers':'*','Access-Control-Allow-Methods':'*'}});return;}
   assert.equal(req.headers().authorization,'Bearer fixture-token');
   if(pathname.endsWith('/video')){media.push({path:pathname,authorization:req.headers().authorization});await route.fulfill({contentType:'video/mp4',body:Buffer.alloc(64),headers:{'Access-Control-Allow-Origin':'*'}});return;}
   const body=req.postData()?req.postDataJSON():null;if(method!=='GET')mutations.push({path:pathname,body});
   let data={};
   if(pathname==='/api/supervisor')data={enabled:false,agents:[],events:[],goals:[],work_receipts:[],jobs:[]};
   else if(pathname==='/api/businesses')data={businesses:['clips','stories','music','social'].map(id=>({id,enabled:id==='stories',running:id==='stories',busy:false,message:id==='stories'?'Running':'Stopped'}))};
   else if(pathname==='/api/stories')data={account_profile_id:profile,busy,job:busy?{stage:'rendering'}:null,projects:compilation?[compilation,...projects]:projects,settings:{max_title_chars:100},compilation:{max_stories:3,opening_s:2.5,between_s:1.5},genres:[],capabilities:{}};
   else if(pathname==='/api/stories/publishing')data={config:{enabled:false,destinations:['youtube'],privacy:'private'},destinations:[{id:'youtube',ready:true}]};
   else if(pathname==='/api/stories/compilations'){
    if(rejectFirst||body.account_profile_id!==profile){rejectFirst=false;await route.fulfill({status:409,json:{detail:body.account_profile_id!==profile?'The Hollow account profile changed. Reload the library before compiling':'Source approval changed. Reload the library and retry.'},headers:{'Access-Control-Allow-Origin':'*'}});return;}
    assert.equal(new Set(body.project_ids).size,body.project_ids.length);
    assert(body.project_ids.every(id=>projects.find(project=>project.id===id)?.account_profile_id===profile));
    busy=true;compilation={id:'collection',kind:'compilation',format:'compilation',title:body.title,account_profile_id:profile,status:'rendering',progress:0,script:'',scenes:[],review:{},output:{},video_url:'',public_copy:{youtube:{title:body.title,description:'Original horror collection'}},compilation:{landscape:body.landscape,sources:body.project_ids.map(id=>({project_id:id,title:projects.find(project=>project.id===id).title}))}};data=compilation;
   }
   else if(pathname==='/api/stories/projects/collection/cancel'){busy=false;Object.assign(compilation,{status:'interrupted',error:'Fixture compilation cancelled',updated_at:Date.now()/1000});data=compilation;}
   else if(pathname==='/api/stories/projects/collection/retry'||pathname==='/api/stories/projects/collection/render'){assembled();data=compilation;}
   else if(pathname==='/api/stories/projects/collection'&&method==='PUT'){assert.deepEqual(Object.keys(body).sort(),['public_copy','title']);Object.assign(compilation,body,{review:{},output:{},video_url:'',updated_at:Date.now()/1000});data=compilation;}
   else if(pathname.startsWith('/api/creative-memory/'))data={account_profile_id:profile,guidance:'',feedback:[],reference_guidance:[]};
   await route.fulfill({json:data,headers:{'Access-Control-Allow-Origin':'*'}});
  });
  await page.goto(`http://127.0.0.1:${server.address().port}`);
  await page.getByRole('button',{name:/^Hollow ·/}).click();await page.getByRole('tab',{name:'Library',exact:true}).click();
  await page.getByRole('button',{name:'Make horror compilation',exact:true}).click();
  assert.equal(await page.getByRole('button',{name:/^Add Other Account/}).count(),0);assert.equal(await page.getByRole('button',{name:'Add Rejected Story to compilation',exact:true}).count(),0);assert.equal(await page.getByRole('button',{name:'Add Unfinished Story to compilation',exact:true}).count(),0);
  await page.getByLabel('Compilation title',{exact:true}).fill('Mobile collection');
  for(const name of ['Old House','Night Radio','Empty Station'])await page.getByRole('button',{name:`Add ${name} to compilation`,exact:true}).click();
  await page.getByRole('button',{name:'Move Empty Station up',exact:true}).click();await page.getByRole('button',{name:'Move Empty Station up',exact:true}).click();await page.getByRole('button',{name:'Remove Night Radio from compilation',exact:true}).click();
  await page.getByRole('switch',{name:'Landscape compilation',exact:true}).click();
  await page.getByRole('tab',{name:'Create',exact:true}).click();await page.getByRole('button',{name:'Keep editing',exact:true}).click();
  assert.equal(await page.getByLabel('Compilation title',{exact:true}).inputValue(),'Mobile collection');
  await page.getByRole('tab',{name:'Create',exact:true}).click();await page.getByRole('button',{name:'Leave editor',exact:true}).click();
  await page.getByRole('tab',{name:'Library',exact:true}).click();
  assert.equal(await page.getByLabel('Compilation title',{exact:true}).inputValue(),'Mobile collection');
  assert.equal(await page.getByRole('switch',{name:'Landscape compilation',exact:true}).isChecked(),false);
  assert.equal(await page.getByRole('button',{name:'Move Empty Station up',exact:true}).isDisabled(),true);
  assert.equal(mutations.length,0,'Navigation does not submit the compilation draft');
  await page.getByRole('button',{name:'Assemble compilation',exact:true}).click();await page.getByText('Source approval changed. Reload the library and retry.',{exact:true}).waitFor();
  assert.equal(await page.getByLabel('Compilation title',{exact:true}).inputValue(),'Mobile collection');
  await page.getByRole('button',{name:'Assemble compilation',exact:true}).click();await page.getByRole('button',{name:'Cancel production',exact:true}).waitFor();
  const compilationCalls=mutations.filter(row=>row.path==='/api/stories/compilations');assert.equal(compilationCalls.length,2);assert.deepEqual(compilationCalls[1].body,{title:'Mobile collection',project_ids:['a3','a1'],landscape:false,account_profile_id:'profile-a'});
  assert(await page.getByRole('button',{name:'Assemble compilation',exact:true}).isDisabled());
  await page.getByRole('tab',{name:'Create',exact:true}).click();await page.getByRole('button',{name:'Keep editing',exact:true}).waitFor({state:'hidden'});
  await page.getByRole('tab',{name:'Library',exact:true}).click();
  assert.equal(await page.getByLabel('Compilation title',{exact:true}).inputValue(),'');
  await page.getByRole('button',{name:'Cancel production',exact:true}).click();await page.getByText('Fixture compilation cancelled',{exact:true}).waitFor();
  await page.getByRole('button',{name:/^Mobile collection interrupted/}).click();
  assert.equal(await page.getByLabel('Narrated manuscript',{exact:true}).count(),0);assert.equal(await page.getByRole('button',{name:'Review story',exact:true}).count(),0);
  assert(await page.getByRole('button',{name:'Reassemble compilation',exact:true}).isEnabled());
  await page.getByRole('button',{name:'Retry production',exact:true}).click();await page.getByText('00:02 – 01:04',{exact:true}).waitFor();
  await page.getByText('This checks source approvals, assembled media and chapter timing. It is not a new creative jury review.',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Preview video',exact:true}).click();await page.locator('video').waitFor();assert.equal(media.length,1);await page.getByRole('button',{name:'Hide video',exact:true}).click();
  assert(await page.getByRole('button',{name:'Publish now',exact:true}).isEnabled());
  await page.getByLabel('Project title',{exact:true}).fill('Renamed collection');await page.getByRole('button',{name:'Save changes',exact:true}).click();
  await page.waitForFunction(()=>{const buttons=[...document.querySelectorAll('[role="button"]')];return buttons.some(button=>button.textContent==='Reassemble compilation'&&button.getAttribute('aria-disabled')!=='true');});
  await page.getByRole('button',{name:'Reassemble compilation',exact:true}).click();
  await page.getByLabel('Compilation title',{exact:true}).fill('Do not mix accounts');await page.getByRole('button',{name:'Add Old House to compilation',exact:true}).click();
  profile='profile-b';await page.getByRole('button',{name:'Reload compilation sources',exact:true}).click();
  await page.getByRole('button',{name:'Add Other Account Woods to compilation',exact:true}).waitFor();assert.equal(await page.getByLabel('Compilation title',{exact:true}).inputValue(),'');await page.getByText('Story order · 0 selected',{exact:true}).waitFor();assert.equal(await page.getByRole('button',{name:'Add Old House to compilation',exact:true}).count(),0);
  await page.getByLabel('Compilation title',{exact:true}).fill('Bound to second profile');for(const name of ['Other Account Woods','Other Account Lake'])await page.getByRole('button',{name:`Add ${name} to compilation`,exact:true}).click();
  profile='profile-a';await page.getByRole('button',{name:'Assemble compilation',exact:true}).click();await page.getByText('The Hollow account profile changed. Reload the library before compiling',{exact:true}).waitFor();assert.equal(mutations.filter(row=>row.path==='/api/stories/compilations').at(-1).body.account_profile_id,'profile-b');
  assert(!mutations.some(row=>row.path.endsWith('/publish')));assert.deepEqual(errors,[]);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.screenshot({path:path.join(root,`artifacts/phone-compilation-${width}.png`)});report.widths.push({width,orderedPayload:true,profileIsolation:true,draftNavigation:true,metadataOnlySave:true,cancelRetry:true,authenticatedPreview:true,noPublication:true,noOverflow:true,pageErrors:errors});await context.close();
 }}finally{await browser.close();}
 fs.writeFileSync(path.join(root,'artifacts/phone-compilations-verification.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(()=>server.close());
