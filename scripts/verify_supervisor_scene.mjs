/* Exercises actual Three.js scene geometry with a stub renderer. No browser or visual QA. */
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const root=new URL('../clipbot/dashboard/static/',import.meta.url);
const frames=new Map(),observed=[],listeners=new Map();let frameId=0,renderer;
class Element{
 constructor(tag){this.tag=tag;this.children=[];this.listeners=new Map();this.style={};this.width=900;this.height=510;}
 get clientWidth(){return this.parent?.clientWidth||this.width;}
 get clientHeight(){return this.parent?.clientHeight||this.height;}
 append(child){child.parent=this;this.children.push(child);}
 remove(){if(this.parent)this.parent.children=this.parent.children.filter(c=>c!==this);this.parent=null;}
 setAttribute(){}
 addEventListener(name,callback){this.listeners.set(name,callback);}
 removeEventListener(name){this.listeners.delete(name);}
 getBoundingClientRect(){return {left:0,top:0,width:this.clientWidth,height:this.clientHeight};}
 getContext(){return {createRadialGradient:()=>({addColorStop(){}}),fillRect(){}};}
}
globalThis.document={hidden:false,createElement:tag=>new Element(tag),addEventListener:(k,v)=>listeners.set(k,v),removeEventListener:k=>listeners.delete(k)};
const motion={matches:false,addEventListener(k,v){this.callback=v;},removeEventListener(){delete this.callback;}};
globalThis.window={devicePixelRatio:3,matchMedia:()=>motion};
globalThis.requestAnimationFrame=callback=>{frames.set(++frameId,callback);return frameId;};
globalThis.cancelAnimationFrame=id=>frames.delete(id);
globalThis.ResizeObserver=class{constructor(callback){this.callback=callback;observed.push(this);}observe(element){this.element=element;}disconnect(){this.disconnected=true;}};
globalThis.IntersectionObserver=class{constructor(callback){this.callback=callback;observed.push(this);}observe(element){this.element=element;}disconnect(){this.disconnected=true;}};
globalThis.__SceneRenderer=class{
 constructor(){renderer=this;this.domElement=new Element('canvas');this.renders=0;}
 setPixelRatio(ratio){this.ratio=ratio;}
 setClearColor(){}
 setSize(){}
 render(scene,camera){this.renders++;this.scene=scene;this.camera=camera;scene.updateMatrixWorld(true);camera.updateMatrixWorld(true);}
 dispose(){this.disposed=true;}
};
let source=readFileSync(new URL('supervisor-neural.js',root),'utf8');
source=source.replace(/import \* as THREE from '[^']+';/,`import * as RealThree from '${new URL('vendor/three/0.186.1/build/three.module.js',root).href}'; const THREE={...RealThree,WebGLRenderer:globalThis.__SceneRenderer};`);
source=source.replace(/from '\.\/supervisor-topology.js[^']*'/,`from '${new URL('supervisor-topology.js',root).href}'`);
source=source.replace(/from '(\.\/[^']+)'/g,(_all,path)=>`from '${new URL(path,root).href}'`);
const {create}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const stage=new Element('stage'),selected=[],states=[];
const view=create(stage,{onSelect:id=>selected.push(id),onStatus:state=>states.push(state)});
assert.equal(renderer.ratio,1.25);
assert.equal(renderer.renders,0,'No offscreen rendering before intersection is known');
const snapshot={enabled:true,state:'waiting_for_business',agents:['director','researcher','engineer','reviewer','curator','evaluator'].map(id=>({id,status:'thinking'})),events:[{id:'history',role:'director',kind:'deferred',at:Date.now()/1000}],goals:[]};
view.update(snapshot,'director');assert.equal(renderer.renders,0);
const resize=observed[0],intersection=observed[1];intersection.callback([{isIntersecting:true}]);
function frame(at=performance.now()+100){const next=frames.entries().next().value;if(next){frames.delete(next[0]);next[1](at);}}
frame();assert(renderer.renders>0);
const field=renderer.scene.children.find(c=>c.isGroup),nodes=field.children.filter(c=>c.userData.agentId);
assert.equal(nodes.length,6);
assert(nodes.every(n=>n.children[0].material.emissiveIntensity===0.42),'Waiting state must override stale thinking states');
const baseCount=field.children.length;view.update(snapshot,'director');assert.equal(field.children.length,baseCount,'History is never replayed');
const now=Date.now()/1000;
const active={...snapshot,state:'investigating',goals:[{id:'goal-one',parent:'director',agent:'engineer',created_at:now}],events:[...snapshot.events,{id:'delegating',role:'director',kind:'delegate',at:now}]};
view.update(active,'engineer');assert.equal(field.children.length,baseCount+2,'One recorded delegation adds an edge and a single packet');
view.update(active,'engineer');assert.equal(field.children.length,baseCount+2,'Repeated snapshot cannot duplicate packets');
stage.width=300;stage.height=340;resize.callback();assert(renderer.camera.position.z>14.5,'Portrait view must move camera back');
for(const node of field.children.filter(c=>c.userData.agentId)){
 const projected=node.getWorldPosition(node.position.clone()).project(renderer.camera);
 assert(Math.abs(projected.x)<0.95&&Math.abs(projected.y)<0.95,'Role must remain within portrait frame');
}
const role=field.children.find(c=>c.userData.agentId==='researcher');
const p=role.getWorldPosition(role.position.clone()).project(renderer.camera);
renderer.domElement.listeners.get('click')({clientX:(p.x+1)*stage.width/2,clientY:(1-p.y)*stage.height/2});
assert.deepEqual(selected,['researcher'],'Scene selection must resolve a real role');
intersection.callback([{isIntersecting:false}]);const paused=renderer.renders;view.update(active,'director');assert.equal(renderer.renders,paused);assert.equal(frames.size,0);
document.hidden=true;listeners.get('visibilitychange')();document.hidden=false;listeners.get('visibilitychange')();assert.equal(frames.size,0,'Returning to tab cannot resume an offscreen scene');
intersection.callback([{isIntersecting:true}]);renderer.domElement.listeners.get('webglcontextlost')({preventDefault(){}});assert.equal(frames.size,0);assert.equal(states.at(-1),'paused');
renderer.domElement.listeners.get('webglcontextrestored')();assert.equal(states.at(-1),'ready');
motion.matches=true;motion.callback();frame(performance.now()+3000);assert.equal(frames.size,0,'Reduced motion must settle to a static frame');
view.dispose();view.dispose();assert(renderer.disposed);assert.equal(stage.children.length,0);assert(observed.every(o=>o.disconnected));assert.equal(frames.size,0);assert.equal(renderer.domElement.listeners.size,0);assert.equal(listeners.size,0);
console.log('PASS: actual Three scene construction, six real roles, waiting-state honesty, event deduplication, portrait framing, ray selection, visibility, context loss/restore, reduced motion and disposal (stub renderer; no visual inspection)');
