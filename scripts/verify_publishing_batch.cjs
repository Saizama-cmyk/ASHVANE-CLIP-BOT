const {chromium} = require('C:/Users/wilco/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs = require('node:fs');

// Mock uploads only, using the isolated preview for its actual shell and sign-in.
(async () => {
  const browser = await chromium.launch({channel:'msedge',headless:true});
  const context = await browser.newContext({viewport:{width:1440,height:1000}});
  const page = await context.newPage(), base = 'http://127.0.0.1:8788';
  const report = {errors:[],checks:[],layouts:[],postRequests:0};
  const check = (name,passed) => {report.checks.push({name,passed:!!passed});};
  page.on('pageerror', error => report.errors.push(error.message));
  const login = await context.request.post(base+'/api/auth/login',{headers:{'X-ClipBot':'1'},data:{password:'preview-only-2026'}});
  if (!login.ok()) throw new Error('Preview login failed: '+login.status());
  const state = await (await context.request.get(base+'/api/state')).json();
  let scheduledCount = 3, connected = true, rejectStart = false, loseResponse = false;
  let job = {status:'idle',total:0,completed:0,posted:0,held:0,failed:0,platforms:[],results:[]};
  const clips = ['aaaaaa','bbbbbb','cccccc'].map((id,index) => ({id,stage:'scheduled',created_at:Date.now()/1000-index,event:{target:{platform:'twitch',login:'tester',display_name:'Test streamer'}},verdict:{title:index===2?'<img src=x onerror=alert(1)>':'Test clip '+index,passed:true,score:8}}));
  await page.route('**/api/state',route => route.fulfill({json:{...state,scheduler:{...state.scheduler,platforms:{youtube:{enabled:connected,configured:connected},discord:{enabled:connected,configured:connected}}}}}));
  await page.route('**/api/clips',route => route.fulfill({json:{clips:clips.slice(0,scheduledCount),posts:[]}}));
  await page.route('**/api/publishing/batch',async route => {
    if (route.request().method()==='POST') {
      report.postRequests++;
      check('Action header sent',route.request().headers()['x-clipbot']==='1');
      await new Promise(resolve => setTimeout(resolve,250));
      if (rejectStart) return route.fulfill({status:400,json:{ok:false,error:'No enabled, connected publishing platforms are ready.'}});
      job = {...job,status:'running',job_id:'test-job',total:scheduledCount,completed:0,posted:0,held:0,failed:0,platforms:['youtube','discord'],results:[],error:''};
      if (loseResponse) return route.fulfill({status:503,json:{error:'Publishing response was lost'}});
      return route.fulfill({json:{ok:true,...job}});
    }
    return route.fulfill({json:{...job,scheduled_count:scheduledCount}});
  });
  try {
    await page.goto(base+'/#clips',{waitUntil:'networkidle'});
    const button = page.locator('#publishBatchStart');
    await page.waitForFunction(() => document.querySelector('#publishBatchHint').textContent.includes('3 scheduled'));
    check('Full queue count shown',await button.isEnabled());
    await button.click();
    check('Start disables repeated clicks',await button.isDisabled());
    await page.waitForFunction(() => document.querySelector('#publishBatchStart').textContent==='Publishing scheduled clips…');
    check('Only one start request',report.postRequests===1);
    await page.locator('nav button[data-view="desk"]').click();
    await page.locator('nav button[data-view="clips"]').click();
    check('Active job survives navigation',await button.isDisabled() && report.postRequests===1);
    job = {...job,completed:1,posted:1,results:[{clip_id:'aaaaaa',results:{youtube:{ok:true,url:'https://youtube.com/watch?v=test'},discord:{ok:false,error:'Webhook expired'}},error:''}]};
    await page.evaluate(() => readPublishingBatch());
    check('Partial platform failure stays visible',(await page.locator('#publishBatchResults').innerText()).includes('Webhook expired'));
    check('Actual progress reflected',await page.locator('#publishBatchProgress').getAttribute('value')==='1');
    job = {...job,status:'complete',completed:3,posted:1,held:1,failed:1,results:[...job.results,{clip_id:'bbbbbb',results:{},error:'Final cut needs review'},{clip_id:'cccccc',results:{},error:'Video is missing <script>alert(1)</script>'}]};
    scheduledCount = 0;
    await page.evaluate(() => readPublishingBatch());
    check('Completion shows all counts',(await page.locator('#publishBatchStatus').innerText()).includes('1 posted · 1 held for review · 1 failed'));
    check('Missing media reason shown',(await page.locator('#publishBatchResults').innerText()).includes('Video is missing'));
    check('Untrusted text escaped',await page.locator('#publishBatchResults img, #publishBatchResults script').count()===0);
    check('Empty queue explains disabled action',await button.isDisabled() && (await page.locator('#publishBatchHint').innerText()).includes('No scheduled clips'));
    scheduledCount = 300;
    await page.evaluate(() => readPublishingBatch());
    check('Count covers more than recent gallery',(await page.locator('#publishBatchHint').innerText()).startsWith('300 scheduled clips'));
    rejectStart = true;
    await button.click();
    await page.waitForFunction(() => document.querySelector('#publishBatchError').textContent.includes('No enabled'));
    check('Start failure remains beside action',await page.locator('#publishBatchError').isVisible());
    check('Failure allows retry',await button.isEnabled());
    rejectStart = false; loseResponse = true;
    await button.click();
    await page.waitForFunction(() => document.querySelector('#publishBatchStart').textContent==='Publishing scheduled clips…');
    check('Lost start response recovers actual active job',await page.locator('#publishBatchError').isHidden() && report.postRequests===3);
    job = {...job,status:'complete'};
    await page.evaluate(() => readPublishingBatch());
    connected = false;
    await page.evaluate(async () => {const r=await api('/api/state');state=r.body;renderPublishingBatch();});
    check('Missing connection explains disabled action',await button.isDisabled() && (await page.locator('#publishBatchHint').innerText()).includes('Connect and enable'));
    for (const width of [1440,900,390,320]) {
      await page.setViewportSize({width,height:1000});
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth>innerWidth);
      report.layouts.push({width,overflow});
      if (width===1440 || width===390) await page.screenshot({path:`artifacts/publishing-batch-${width}.png`,fullPage:true});
    }
    job = {...job,status:'running',total:3,completed:1,current_id:'bbbbbb'};
    await page.reload({waitUntil:'networkidle'});
    await page.waitForFunction(() => document.querySelector('#publishBatchStart').textContent==='Publishing scheduled clips…');
    check('Reload reconnects to existing job without publishing',await button.isDisabled() && report.postRequests===3);
  } finally {
    fs.writeFileSync('artifacts/publishing-batch-browser-report.json',JSON.stringify(report,null,2));
    console.log(JSON.stringify(report));await browser.close();
  }
  if (report.errors.length || report.checks.some(c=>!c.passed) || report.layouts.some(l=>l.overflow)) process.exitCode=1;
})().catch(error=>{console.error(error);process.exit(1);});
