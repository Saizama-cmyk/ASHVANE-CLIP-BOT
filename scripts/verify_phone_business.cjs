const { chromium } = require('C:/Users/wilco/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert = require('node:assert/strict');
(async () => {
 const browser = await chromium.launch({headless:true,channel:"chrome"});
 for (const width of [320,390]) {
  const context = await browser.newContext({viewport:{width,height:844},reducedMotion:'reduce'});
  const page = await context.newPage(); const requests=[], writes=[], errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>{localStorage.setItem('ashvane.host','http://fixture.test');localStorage.setItem('ashvane.token','fixture-token');});
  await page.route('http://fixture.test/**', async route=>{
   const req=route.request(), path=new URL(req.url()).pathname;requests.push(path);
   if(req.method()!=='GET' && req.method()!=='OPTIONS')writes.push({path,method:req.method(),body:req.postDataJSON()});
   let data={};
   if(path==='/api/stories')data={settings:{default_genre:'paranormal',default_format:'still'},genres:[{id:'paranormal',label:'Paranormal'}],projects:[],capabilities:{}};
   if(path==='/api/stories/publishing')data={config:{enabled:false,destinations:[],privacy:'private'},destinations:[{id:'youtube',label:'YouTube',ready:true,account_label:'Story channel'}]};
   if(path==='/api/stories/accounts')data={accounts:{youtube_client_id:'story-app',youtube_client_secret:'********',instagram_token:'********'},oauth:{youtube:true,tiktok:false},destinations:[{id:'youtube',ready:true,account_id:'story-channel-id',account_label:'Story channel'}],app_credentials:{youtube:{inherited:false}}};
   if(path.startsWith('/api/account-profiles/stories'))data={active_profile_id:'default',profiles:[{id:'default',name:'Story channel',description:'',public_handles:{},accounts:{youtube_client_id:'story-app',youtube_client_secret:'********'},connections:{youtube:{ready:true,account_label:'Story channel identity',account_id:'story-channel-id'}}}]};
   if(path==='/api/settings/schema')data={properties:{stories:{$ref:'#/$defs/Stories'},accounts:{title:'Clip accounts'},story_accounts:{title:'Story accounts'},capture:{title:'Capture'}},$defs:{Stories:{properties:{voice:{title:'Narrator voice',type:'string'},auto_render:{title:'Render approved story drafts',type:'boolean'}}}}};
   if(path==='/api/settings')data={stories:{voice:'Fixture narrator',auto_render:true}};
   await route.fulfill({status:200,contentType:'application/json',headers:{'Access-Control-Allow-Origin':'*','Access-Control-Allow-Headers':'*','Access-Control-Allow-Methods':'*'},body:JSON.stringify(data)});
  });
  await page.route('https://api.github.com/**',route=>route.fulfill({json:{}}));
  await page.goto(process.env.ASHVANE_PHONE_PREVIEW || 'http://127.0.0.1:8139');

  await page.getByRole('button',{name:/Hollow.*Scary stories/}).click();
  await page.getByRole('tab',{name:'Create',exact:true}).waitFor();
  await page.getByLabel('Story direction · optional').waitFor();
  assert.equal(await page.getByRole('tab',{name:'Desk',exact:true}).count(),0);
  const at=requests.length;
  await page.waitForTimeout(6500);
  assert(!requests.slice(at).includes('/api/state'),'Stories must not poll clip state');
  assert(!requests.slice(at).some(x=>x.startsWith('/api/research')),'Stories must not poll research');
  await page.getByRole('tab',{name:'Library',exact:true}).click();
  await page.getByText('Your first story starts here',{exact:true}).waitFor();
  await page.getByRole('tab',{name:'Accounts',exact:true}).click();
  await page.getByText('Story channel identity',{exact:true}).waitFor();
  assert.equal(await page.getByLabel('OAuth client secret',{exact:true}).inputValue(),'');
  await page.getByLabel('OAuth client ID',{exact:true}).fill('changed-story-app');
  page.once('dialog',dialog=>dialog.dismiss());
  await page.getByRole('button',{name:/Surge.*Streamer clips/}).click();
  assert.equal(await page.getByLabel('OAuth client ID',{exact:true}).inputValue(),'changed-story-app');
  await page.getByRole('button',{name:'Save account profile',exact:true}).click();
  await page.getByText('Account profile saved.',{exact:true}).waitFor();
  assert.deepEqual(writes.find(x=>x.method==='PATCH').body,{accounts:{youtube_client_id:'changed-story-app'}});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.screenshot({path:`artifacts/phone-business-accounts-${width}.png`});
  await page.getByRole('button',{name:/Surge.*Streamer clips/}).click();
  await page.getByRole('tab',{name:'Desk',exact:true}).waitFor();
  await page.getByRole('tab',{name:'Research',exact:true}).click();
  await page.waitForTimeout(300);
  await page.getByRole('button',{name:/Hollow.*Scary stories/}).click();
  await page.getByText('Story channel identity',{exact:true}).waitFor();
  await page.getByRole('tab',{name:'Settings',exact:true}).click();
  await page.getByLabel('Narrator voice',{exact:true}).waitFor();
  assert.equal(await page.getByText('Capture',{exact:true}).count(),0);
  assert.equal(await page.getByText('All settings',{exact:true}).count(),0);
  await page.getByRole('button',{name:/Surge.*Streamer clips/}).click();
  await page.getByRole('tab',{name:'Research',exact:true}).waitFor();
  await page.waitForTimeout(350);
  assert.match(await page.locator('body').innerText(),/Surge.*Research/);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'horizontal viewport overflow');
  assert.deepEqual(errors,[]);
  await page.screenshot({path:`artifacts/phone-business-${width}.png`});
  console.log(`${width}px: business navigation, remembered screens, isolated polling/settings, masked secret preservation passed`);
  await context.close();
 }
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});

