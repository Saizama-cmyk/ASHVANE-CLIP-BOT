/* Headless DOM contract check. No browser, desktop input, engine or real business mutation. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs');
const source=fs.readFileSync('clipbot/dashboard/static/business.js','utf8');
const html=fs.readFileSync('clipbot/dashboard/static/index.html','utf8');
assert(html.indexOf('id="businessRuntime"')>html.indexOf('<div class="content">'));
assert.equal((html.match(/data-business-run="/g)||[]).length,4);
assert(!source.includes("byId('businessChoices').append(runtime)"));
class Control{
 constructor(id){this.dataset={businessRun:id};this.attrs={};this.disabled=true;this.label={textContent:'Run'};}
 setAttribute(k,v){this.attrs[k]=v;}
 getAttribute(k){return this.attrs[k]||'';}
 querySelector(){return this.label;}
 closest(selector){return selector==='[data-business-run]'?this:null;}
}
const cards=['clips','stories','music','social'].map((id,i)=>{
 const button=new Control(id),name={textContent:['Surge','Hollow','Resonance','Social Studio'][i]},small={textContent:'Connecting…'};
 return {dataset:{runtimeBusiness:id},button,name,small,querySelector:s=>s==='small'?small:s==='[data-business-open]'?name:button};
});
const callbacks={},docCallbacks={},notices=[],requests=[],opened=[];
const runtime={attrs:{},addEventListener:(name,f)=>callbacks[name]=f,
 setAttribute(k,v){this.attrs[k]=v;},removeAttribute(k){delete this.attrs[k];},
 querySelectorAll:s=>s==='[data-runtime-business]'?cards:s.includes('[data-enabled]')?cards.map(c=>c.button).filter(b=>b.dataset.enabled!==undefined):cards.map(c=>c.button)};
const document={hidden:false,addEventListener:(name,f)=>docCallbacks[name]=f};
const window={switchBusiness:id=>opened.push(id),dispatchEvent:event=>requests.push({event:event.detail})};
function request(path,options={}){return new Promise((resolve,reject)=>requests.push({path,options,resolve,reject}));}
function status(id,text,error=false){notices.push({text,error});}
const start=source.indexOf("  const runtime=byId('businessRuntime')"),end=source.indexOf('  async function request(',start);
assert(start>0&&end>start);
const scope=new Function('byId','request','status','document','window','CustomEvent','setTimeout','clearTimeout',source.slice(start,end)+'\nreturn {loadRuntime};')(
 ()=>runtime,request,status,document,window,class{constructor(name,init){this.detail=init.detail;}},()=>1,()=>{});
const state=enabled=>({businesses:cards.map(c=>({id:c.dataset.runtimeBusiness,name:c.name.textContent,enabled:c.dataset.runtimeBusiness==='clips'?enabled:false,running:c.dataset.runtimeBusiness==='clips'?enabled:false}))});
const click=button=>callbacks.click({target:button,stopPropagation(){}});
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 const first=scope.loadRuntime();requests.at(-1).resolve(state(true));await first;
 assert.equal(cards[0].button.attrs['aria-checked'],'true');assert(cards.every(c=>!c.button.disabled));
 const stale=scope.loadRuntime(),staleGet=requests.at(-1);
 const changing=click(cards[0].button),post=requests.at(-1);
 assert.equal(post.path,'/api/businesses/clips');assert.deepEqual(post.options.json,{enabled:false});
 assert(cards.every(c=>c.button.disabled));
 await click(cards[1].button);assert.equal(requests.filter(r=>r.options?.method==='POST').length,1);
 post.resolve(state(false));await flush();assert.equal(cards[0].button.attrs['aria-checked'],'false');
 staleGet.resolve(state(true));await stale;await flush();
 assert.equal(cards[0].button.attrs['aria-checked'],'false','Stale GET must not roll back a confirmed stop');
 requests.filter(r=>r.path==='/api/businesses').at(-1).resolve(state(false));await changing;
 assert(cards.every(c=>!c.button.disabled));assert.equal(cards[0].button.label.textContent,'Run');
 const before=requests.length;await callbacks.click({target:{dataset:{businessOpen:'music'},closest:s=>s==='[data-business-open]'?{dataset:{businessOpen:'music'}}:null}});
 assert.deepEqual(opened,['music']);assert.equal(requests.length,before,'Opening a workspace must not start it');
 const failed=click(cards[0].button);requests.at(-1).reject(new Error('Disconnected during change'));await flush();
 requests.filter(r=>r.path==='/api/businesses').at(-1).resolve(state(false));await failed;
 assert(notices.at(-1).error&&notices.at(-1).text.includes('Disconnected'),'A failed action must remain visible after state refresh');
 const unknown=scope.loadRuntime();requests.at(-1).resolve({businesses:[]});await unknown;
 assert(cards.every(c=>c.button.disabled),'Unknown state must disable switching');
 console.log('PASS: four permanent switches, confirmed states, independent navigation, guarded actions, stale-response handling, errors and unknown states');
})().catch(error=>{console.error(error);process.exitCode=1;});
