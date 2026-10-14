/* Run the actual controller with controlled requests; no browser or account access. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes=new Map(),events=new Map(),timers=new Map(),requests=[];let sequence=0;
const element=id=>{if(!nodes.has(id))nodes.set(id,{id,value:id==='growthRange'?'all':id==='growthPlatform'?'all':'',textContent:'',innerHTML:'',disabled:false,hidden:false,dataset:{},classList:{contains:()=>true,toggle(){}},setAttribute(){},querySelectorAll:()=>[],addEventListener(name,fn){this[name]=fn;}});return nodes.get(id);};
const window={ashvaneUI:{growth_request_timeout_s:20,youtube_sync_timeout_s:120},addEventListener:(name,fn)=>events.set(name,fn)};
const context={window,document:{hidden:false,getElementById:element,addEventListener(){}},URL,Date,Number,Map,Set,JSON,Math,AbortController,
  MutationObserver:class{observe(){}},esc:value=>String(value),
  setTimeout:(fn,ms)=>{const id=++sequence;timers.set(id,{fn,ms});return id;},clearTimeout:id=>timers.delete(id),
  api:(path,options)=>new Promise((resolve,reject)=>{const row={path,options,resolve,reject};requests.push(row);options.signal.addEventListener('abort',()=>{const error=new Error('aborted');error.name='AbortError';reject(error);});})};
vm.runInNewContext(fs.readFileSync('clipbot/dashboard/static/growth.js','utf8'),context);
const settle=()=>new Promise(resolve=>setImmediate(resolve));
const response=identity=>({ok:true,status:200,body:{account_profile_id:identity,posts:[],analytics:{},local:{},supervisor:{},youtube_library:{},poll_s:5}});
async function run(){
  assert.equal(requests.length,1);
  events.get('accountprofilechange')({detail:{business:'clips',profile_id:'default'}});
  await settle();
  for(const [id,timer]of [...timers])if(timer.ms===0){timers.delete(id);timer.fn();}
  await settle();assert.equal(requests.length,2);
  requests[1].resolve(response('default'));await settle();
  assert(!element('growthKpis').innerHTML.includes('Loading this profile'));
  const saved=element('growthKpis').innerHTML;
  events.get('accountprofilechange')({detail:{business:'clips',profile_id:'default'}});
  assert.equal(element('growthKpis').innerHTML,saved,'Same-profile reconnect must preserve loaded data');
  assert.equal(requests.length,3);
  for(const [id,timer]of [...timers])if(timer.ms===20000){timers.delete(id);timer.fn();}
  await settle();assert.match(element('growthNotice').textContent,/deadline/);
  assert.equal(element('growthRefresh').disabled,false);
  events.get('accountprofilechange')({detail:{business:'clips',profile_id:'a'.repeat(32)}});
  assert(element('growthKpis').innerHTML.includes('Loading this profile'));
  requests.at(-1).resolve(response('a'.repeat(32)));await settle();
  assert(!element('growthKpis').innerHTML.includes('Loading this profile'));
  console.log('PASS: reconnect during load, same-profile preservation, bounded refresh and profile recovery');
}
run().catch(error=>{console.error(error);process.exitCode=1;});
