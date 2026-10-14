/* Fixture-only phone Core QA. Starts an ephemeral static server; contacts no live engines. */
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const {chromium}=require('C:/Users/wilco/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root=path.resolve(__dirname,'..'),build=path.join(root,'artifacts/phone-interstellar-export');
const mime={'.html':'text/html','.js':'text/javascript','.ttf':'font/ttf','.png':'image/png','.json':'application/json','.map':'application/json'};
const server=http.createServer((req,res)=>{
  const relative=decodeURIComponent(new URL(req.url,'http://localhost').pathname).replace(/^\/+/,''),target=path.resolve(build,relative||'index.html');
  if(!target.startsWith(build+path.sep)){res.writeHead(403);res.end();return;}
  fs.readFile(target,(error,body)=>{if(error){res.writeHead(404);res.end();return;}res.setHeader('Content-Type',mime[path.extname(target)]||'application/octet-stream');res.end(body);});
});
(async()=>{
  const helpers=await import('data:text/javascript;base64,'+fs.readFileSync(path.join(__dirname,'coreSceneData.js')).toString('base64'));
  const safe=helpers.sceneMessage({token:'never-in-scene',agents:[{id:'director',name:'</script><script>bad()</script>',task:'private-task',instructions:'private-instructions',authorization:'secret'}],events:[],goals:[]},'director');
  assert(!JSON.stringify(safe).includes('never-in-scene')&&!JSON.stringify(safe).includes('private-task')&&!JSON.stringify(safe).includes('private-instructions'));
  assert(!helpers.safeSceneJSON(safe).includes('<'),'Injected JSON escapes HTML delimiters');
  assert.equal(helpers.acceptSceneMessage(JSON.stringify({type:'run',goal:'untrusted'}),safe.snapshot),null,'Scene cannot ask native API to run');
  assert.equal(helpers.acceptSceneMessage(JSON.stringify({type:'ashvane-core-select',id:'missing'}),safe.snapshot),null,'Scene cannot select an unknown agent');
  assert.equal(helpers.acceptSceneMessage('x'.repeat(1025),safe.snapshot),null,'Oversized scene messages are rejected');
  const receiptOnly=helpers.sceneSnapshot({work_receipts:[
    {id:'done',role:'engineer',kind:'tool_completed',at:1,summary:'private-summary',code:'private-code',authorization:'Bearer private'},
    {id:'failed',role:'engineer',kind:'tool_failed',at:2,error:'private-error'},
    {id:'requested',role:'engineer',kind:'tool_requested',at:3},
    {id:'invalid',role:'engineer',kind:'tool_completed',at:'unverified-time'}]});
  assert.deepEqual(receiptOnly.work_receipts,[{id:'done',role:'engineer',kind:'tool_completed',at:1},{id:'failed',role:'engineer',kind:'tool_failed',at:2}]);
  assert(!JSON.stringify(receiptOnly).includes('private'),'Receipt display metadata excludes summaries, errors, code and secrets');
  assert.equal(helpers.sceneSnapshot({work_receipts:Array.from({length:200},(_,index)=>({id:`receipt-${index}`,role:'engineer',kind:'tool_completed',at:1}))}).work_receipts.length,128);
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const browser=await chromium.launch({headless:true,channel:'chrome'}), report={fixture:true,widths:[],realEnginesContacted:false,physicalDevicesTested:false};
  try{
    for(const width of [320,390]){
      const context=await browser.newContext({viewport:{width,height:844},reducedMotion:width===320?'reduce':'no-preference'}),page=await context.newPage();
      const calls=[],mutations=[],errors=[],staticAuth=[];
      let stallMaster=false,releaseMaster;
      let supervisor={enabled:false,state:'disabled',active_job:null,blocking_reason:'Fixture decision model is unavailable',blocking_since:1700000000,
        agents:[{id:'director',name:'Director',status:'idle',instructions:'Choose useful work from verified evidence.',task:''},{id:'engineer',name:'Engineer',status:'idle',instructions:'Make inspectable isolated changes.',task:JSON.stringify({task:{nested:'fixture'}})}],
        goals:[{id:'goal-1',parent:'director',agent:'engineer',goal:'Verify the fixture change',created_at:1700000000}],
        work_receipts:[{id:'receipt-1',role:'engineer',kind:'tool_completed',summary:'Fixture isolated check completed',passed:true,at:1700000000},{id:'receipt-failed',role:'engineer',kind:'tool_failed',summary:'Fixture isolated check failed',passed:false,at:1700000000}],events:[],jobs:[]};
      page.on('pageerror',error=>{errors.push(error.message);console.error(error.stack);});
      await page.addInitScript(()=>{localStorage.setItem('ashvane.host','http://fixture.test');localStorage.setItem('ashvane.token','fixture-session-token');});
      await page.route('https://api.github.com/**',route=>route.fulfill({json:{}}));
      await page.route('http://fixture.test/**',async route=>{
        const request=route.request(),pathname=new URL(request.url()).pathname,method=request.method();
        if(method==='OPTIONS'){await route.fulfill({status:204,headers:{'Access-Control-Allow-Origin':'*','Access-Control-Allow-Headers':'*','Access-Control-Allow-Methods':'*'}});return;}
        if(pathname.startsWith('/static/')){
          staticAuth.push(request.headers().authorization||'');
          const target=path.resolve(root,'clipbot/dashboard',pathname.slice(1));
          if(!target.startsWith(path.join(root,'clipbot/dashboard/static')+path.sep)){await route.fulfill({status:403});return;}
          try{
            let bytes=fs.readFileSync(target);
            if(pathname==='/static/supervisor-neural.js'){
              // Fixture-only probes at the real renderer's input and packet emission.
              // No production instrumentation or renderer behavior is changed.
              let source=bytes.toString();
              const guard='if (prefersReducedMotion() || !visible || !node) return;';
              const update='update(snapshot, selection) {';
              const packet='packets.push({mesh, curve, start: performance.now(), duration: 1300});';
              const settled='renderOnce();\n    if (!reduced || packets.length) requestFrame();';
              assert([guard,update,packet,settled,'const progress = '].every(anchor=>source.includes(anchor)),'Renderer probe locations must match actual source');
              source=source.replace(guard,guard+' window.__phoneActualPackets=(window.__phoneActualPackets||0)+1;');
              source=source.replace(update,update+' window.__phoneRendererSnapshot=snapshot;');
              source=source.replace(packet,packet.replace('performance.now()','performance.now()+(window.__phonePacketFutureStartMs||0)'));
              source=source.replace('const progress = ','window.__phoneNegativePacketFrames=(window.__phoneNegativePacketFrames||0)+(now<packet.start?1:0); const progress = ');
              source=source.replace(settled,'window.__phonePendingPacketCount=packets.length; '+settled);
              bytes=Buffer.from(source);
            }
            await route.fulfill({body:bytes,contentType:mime[path.extname(target)]||'application/octet-stream'});
          }catch{await route.fulfill({status:404});}
          return;
        }
        calls.push({path:pathname,method,authorization:request.headers().authorization,action:request.headers()['x-clipbot']});
        const body=request.postData()?request.postDataJSON():null;
        if(method!=='GET')mutations.push({path:pathname,body});
        let data={};
        if(pathname==='/api/supervisor')data=supervisor;
        else if(pathname==='/api/supervisor/master'){supervisor={...supervisor,enabled:body.enabled,state:body.enabled?'queued':'disabled',pending_job:body.enabled?{id:'queued-fixture-job',goal:'Queued fixture investigation',status:'queued'}:null};data=supervisor;if(stallMaster)await new Promise(resolve=>{releaseMaster=resolve;});}
        else if(pathname==='/api/supervisor/run'){supervisor={...supervisor,state:'investigating',active_job:{id:'fixture-job',goal:body.goal,status:'running'},blocking_reason:''};data={ok:true,job_id:'fixture-job'};}
        else if(pathname==='/api/supervisor/cancel'){supervisor={...supervisor,state:'idle',active_job:null,pending_job:null,jobs:[{id:'fixture-job',goal:'Verify mobile Core controls',status:'cancelled',created_at:1700000000}]};data=supervisor;}
        else if(pathname==='/api/businesses')data={businesses:['clips','stories','music','social'].map(id=>({id,enabled:false,running:false,busy:false,message:'Stopped by choice'}))};
        else if(pathname==='/api/stories')data={settings:{},genres:[],projects:[],capabilities:{}};
        else if(pathname==='/api/stories/publishing')data={config:{},destinations:[]};
        else if(pathname==='/api/music/status')data={ready:false,busy:false,message:'Fixture stopped'};
        else if(pathname==='/api/music/songs')data={songs:[]};
        else if(pathname==='/api/music/renders')data={renders:[]};
        else if(pathname==='/api/music/reaper/status')data={ready:false,projects:[]};
        else if(pathname==='/api/social/clients')data={clients:[]};
        else if(pathname==='/api/research')data={sources:[],ideas:[]};
        await route.fulfill({contentType:'application/json',headers:{'Access-Control-Allow-Origin':'*'},body:JSON.stringify(data)});
      });
      await page.goto(`http://127.0.0.1:${server.address().port}`);
      await page.waitForTimeout(1600);
      await page.getByRole('button',{name:'Inspect Engineer',exact:true}).waitFor();
      assert.equal(mutations.length,0,'Opening Core must not start work or toggle businesses');
      assert(await page.getByRole('button',{name:'Run improvement cycle',exact:true}).isDisabled());
      await page.getByRole('button',{name:'Inspect Engineer',exact:true}).click();
      await page.getByText('A structured investigation task is assigned.',{exact:true}).waitFor();
      assert(await page.getByText('Fixture isolated check completed',{exact:true}).count()===2);
      await page.getByText('Tool completions: 1 · failures: 1',{exact:true}).waitFor();
      await page.getByRole('switch',{name:'Supervisor master switch',exact:true}).click();
      await page.waitForFunction(()=>document.querySelector('[aria-label="Supervisor master switch"]')?.checked===true);
      await page.getByText('Queued fixture investigation',{exact:true}).waitFor();
      assert(await page.getByRole('button',{name:'Run improvement cycle',exact:true}).isDisabled());
      assert.equal(await page.getByLabel('Improvement goal · optional',{exact:true}).isEditable(),false);
      await page.getByRole('button',{name:'Cancel supervisor work',exact:true}).click();
      await page.getByText('Cancellation requested. The PC is draining owned work.',{exact:true}).waitFor();
      await page.getByLabel('Improvement goal · optional',{exact:true}).fill('Verify mobile Core controls');
      await page.getByRole('button',{name:'Run improvement cycle',exact:true}).click();
      await page.getByRole('button',{name:'Cancel supervisor work',exact:true}).waitFor();
      await page.getByRole('button',{name:'Cancel supervisor work',exact:true}).click();
      await page.getByText('Cancellation requested. The PC is draining owned work.',{exact:true}).waitFor();
      assert.deepEqual(mutations.map(row=>row.path),['/api/supervisor/master','/api/supervisor/cancel','/api/supervisor/run','/api/supervisor/cancel']);
      assert.deepEqual(mutations[2].body,{goal:'Verify mobile Core controls'});
      assert(calls.every(row=>row.authorization==='Bearer fixture-session-token'&&row.action==='1'),'Native API calls must keep bearer and action headers');
      assert(staticAuth.every(value=>!value),'Scene requests must never carry the bearer token');
      if(width===390){
        const frame=page.frames().find(item=>item.url().includes('supervisor-phone.html'));
        assert(frame,'Interactive scene frame exists');
        await frame.locator('body.ready canvas').waitFor();
        await page.locator('iframe[title="Interactive agent constellation"]').scrollIntoViewIfNeeded();
        await page.waitForTimeout(150);
        const baseSnapshot=helpers.sceneSnapshot(supervisor);
        const sendScene=async value=>frame.evaluate(snapshot=>window.dispatchEvent(new MessageEvent('message',{source:window,origin:location.origin,data:{type:'ashvane-core-snapshot',snapshot,selected:'engineer',active:true}})),value);
        const packetCount=()=>frame.evaluate(()=>window.__phoneActualPackets||0);
        await sendScene(baseSnapshot);
        const baseline=await packetCount();
        const now=Date.now()/1000;
        const requestOnly={...baseSnapshot,events:[{id:'requested-only',role:'engineer',kind:'tool_requested',at:now}],work_receipts:[...baseSnapshot.work_receipts,{id:'misfiled-request',role:'engineer',kind:'tool_requested',at:now}]};
        await sendScene(requestOnly);
        assert.equal(await packetCount(),baseline,'Requested events and misfiled requests must not animate receipt packets');
        const completion={id:'fresh-completion',role:'engineer',kind:'tool_completed',at:now,summary:'must-not-enter-renderer',code:'must-not-enter-renderer'};
        await frame.evaluate(()=>{window.__phonePacketFutureStartMs=250;});
        await sendScene({...requestOnly,work_receipts:[...requestOnly.work_receipts,completion]});
        assert.equal(await packetCount(),baseline+1,'A new actual completion receipt emits one real renderer packet');
        await frame.waitForFunction(()=>window.__phoneNegativePacketFrames>0);
        await frame.evaluate(()=>{window.__phonePacketFutureStartMs=0;});
        const failure={id:'fresh-failure',role:'engineer',kind:'tool_failed',at:now};
        const updated={...requestOnly,work_receipts:[...requestOnly.work_receipts,completion,failure]};
        await sendScene(updated);
        assert.equal(await packetCount(),baseline+2,'A new actual failure receipt emits a receipt packet');
        await sendScene(updated);
        assert.equal(await packetCount(),baseline+2,'Repeated receipt snapshots do not replay packets');
        await frame.waitForFunction(()=>window.__phonePendingPacketCount===0);
        assert.deepEqual(errors,[],'Receipt packets survive RAF timestamps before their start and settle without scene errors');
        const forwarded=await frame.evaluate(()=>window.__phoneRendererSnapshot.work_receipts);
        assert(forwarded.every(row=>Object.keys(row).sort().join(',')==='at,id,kind,role'),'Public shell independently allowlists receipt fields');
        assert(!forwarded.some(row=>row.kind==='tool_requested'),'Public shell rejects requested records from receipt channel');
        assert(!(await frame.content()).includes('fixture-session-token'),'Scene HTML has no session token');
        await frame.evaluate(()=>parent.postMessage(JSON.stringify({type:'ashvane-core-select',id:'director'}),new URL(location.href).searchParams.get('parent_origin')));
        await page.getByText('Choose useful work from verified evidence.',{exact:true}).waitFor();
      }
      if(width===320){
        stallMaster=true;
        await page.getByRole('switch',{name:'Supervisor master switch',exact:true}).click();
        await page.waitForFunction(()=>document.querySelector('[aria-label="Supervisor master switch"]')?.disabled===true);
        await page.evaluate(()=>{Object.defineProperty(document,'visibilityState',{configurable:true,value:'hidden'});document.dispatchEvent(new Event('visibilitychange'));});
        await page.waitForTimeout(100);
        await page.evaluate(()=>{Object.defineProperty(document,'visibilityState',{configurable:true,value:'visible'});document.dispatchEvent(new Event('visibilitychange'));});
        releaseMaster();stallMaster=false;
        await page.waitForFunction(()=>{const toggle=document.querySelector('[aria-label="Supervisor master switch"]');return toggle&&!toggle.checked&&!toggle.disabled;});
      }
      await page.getByRole('tab',{name:'Core',exact:true}).click();
      await page.getByText('The Core',{exact:true}).scrollIntoViewIfNeeded();
      await page.screenshot({path:path.join(root,`artifacts/phone-core-${width}.png`)});
      const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth);
      assert(!overflow,'Phone must not overflow horizontally');
      await page.getByRole('button',{name:/^Hollow ·/}).click();
      await page.getByRole('tab',{name:'Create',exact:true}).waitFor();
      const after=calls.length; await page.waitForTimeout(6500);
      assert(!calls.slice(after).some(row=>row.path==='/api/supervisor'),'Leaving Core stops supervisor polling');
      assert(!mutations.some(row=>row.path.startsWith('/api/businesses/')),'Workspace navigation never starts an engine');
      await page.getByRole('button',{name:/^Resonance ·/}).click();
      await page.getByLabel('Musical direction · optional',{exact:true}).waitFor();
      await page.getByText('Reference limits are unavailable. Refresh references or update the PC app. Written direction and lyrics remain available.',{exact:true}).waitFor();
      assert.deepEqual(errors,[]);
      report.widths.push({width,coreActions:true,pendingJobCancellation:true,authenticated:true,sceneTokenFree:true,pollingStopped:true,backgroundRecovery:width===320,overflow:false,pageErrors:errors});
      await context.close();
    }
    report.sceneAllowlistAndEscape=true;
    report.actualReceiptPackets=true;
    report.rafBeforeReceiptStart=true;
    fs.writeFileSync(path.join(root,'artifacts/phone-core-verification.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(()=>server.close());
