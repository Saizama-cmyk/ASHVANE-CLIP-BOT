/* Three-dimensional view of the reported roster and newly recorded events. */
import * as THREE from './vendor/three/0.186.1/build/three.module.js';
import {EffectComposer} from './vendor/three/0.186.1/examples/jsm/postprocessing/EffectComposer.js';
import {RenderPass} from './vendor/three/0.186.1/examples/jsm/postprocessing/RenderPass.js';
import {UnrealBloomPass} from './vendor/three/0.186.1/examples/jsm/postprocessing/UnrealBloomPass.js';
import {OutputPass} from './vendor/three/0.186.1/examples/jsm/postprocessing/OutputPass.js';
import {createHorizon} from './supervisor-horizon.js?v=7cf2d928c94adf85';
import {roleEdges, rolesOperational, nextEventPackets, nextDelegations} from './supervisor-topology.js?v=1a138ad362aed4bb';

const PALETTE = {
  director: 0xffc27d, researcher: 0x75ddcf, engineer: 0xc29bff,
  reviewer: 0xff9b92, curator: 0xe7d49d, evaluator: 0x9ee6b7,
};
const FALLBACK_COLORS = [0x8dbfff, 0xe5a7d1, 0xb4d4a2, 0xf2b598];
const FRAME_MS = 1000 / 24;
const MAX_PIXEL_RATIO = 1.25;
const MAX_PACKETS = 12;
const prefersReducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const list = value => Array.isArray(value) ? value : [];

export function create(container, {onSelect = () => {}, onStatus = () => {}} = {}) {
  const canvasHost = document.createElement('div');
  canvasHost.className = 'supervisor-neural-canvas';
  canvasHost.setAttribute('aria-hidden', 'true');
  container.append(canvasHost);
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({alpha: true, antialias: true, powerPreference: 'low-power'});
  } catch (error) {
    canvasHost.remove();
    throw error;
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, MAX_PIXEL_RATIO));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.setClearColor(0x07121b, 0);
  canvasHost.append(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
  camera.position.set(0, 0.3, 14.5);
  camera.lookAt(0, 0, 0);
  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  const field = new THREE.Group();
  scene.add(field);
  scene.add(new THREE.AmbientLight(0xb9d5e1, 1.6));
  const key = new THREE.PointLight(0xffbb76, 23, 20);
  key.position.set(-3, 3, 5);
  scene.add(key);
  const rim = new THREE.PointLight(0x62bfdc, 18, 20);
  rim.position.set(4, -2, -3);
  scene.add(rim);
  let composer=null,bloom=null;
  if(renderer.isWebGLRenderer){
    try{
      composer=new EffectComposer(renderer);
      composer.addPass(new RenderPass(scene,camera));
      bloom=new UnrealBloomPass(new THREE.Vector2(800,500),.54,.35,1.05);
      composer.addPass(bloom);composer.addPass(new OutputPass());composer.setPixelRatio(1);
    }catch(error){composer?.dispose();composer=null;console.warn('Core post-processing unavailable; direct rendering retained.',error);}
  }

  const glowTexture = (() => {
    const c = document.createElement('canvas');
    c.width = c.height = 64;
    const x = c.getContext('2d');
    const g = x.createRadialGradient(32, 32, 1, 32, 32, 32);
    g.addColorStop(0, 'rgba(255,255,255,1)');
    g.addColorStop(0.16, 'rgba(255,255,255,.82)');
    g.addColorStop(0.44, 'rgba(255,255,255,.2)');
    g.addColorStop(1, 'rgba(255,255,255,0)');
    x.fillStyle = g; x.fillRect(0, 0, 64, 64);
    return new THREE.CanvasTexture(c);
  })();
  const sprite = (color, size, opacity = 1) => {
    const material = new THREE.SpriteMaterial({map: glowTexture, color, transparent: true,
      opacity, depthWrite: false, blending: THREE.AdditiveBlending});
    const object = new THREE.Sprite(material);
    object.scale.set(size, size, 1);
    return object;
  };
  const material = (color, opacity) => new THREE.MeshBasicMaterial({
    color, transparent: true, opacity, depthWrite: false, side: THREE.DoubleSide,
    blending: THREE.AdditiveBlending,
  });
  const line = (curve, color, opacity, radius = 0.009) => {
    const mesh = new THREE.Mesh(new THREE.TubeGeometry(curve, 28, radius, 4, false), material(color, opacity));
    field.add(mesh);
    return mesh;
  };
  const center = new THREE.Vector3(0, 0, 0);
  const horizon=createHorizon(THREE),hub=horizon.group;
  field.add(hub);

  let nodes = new Map(), packets = [], seenEvents = new Set(), seenGoals = new Set(), baselineSet = false;
  let topology = '', selected = '', inViewport = false, visible = false, frame = 0, lastFrame = 0;
  let destroyed = false, contextLost = false, motionQuery;
  let drag=null,dragged=false,zoom=1;
  const labels=document.createElement('div');labels.className='core-space-labels';labels.setAttribute('aria-hidden','true');canvasHost.append(labels);
  const chooseColor = (id, index) => PALETTE[id] || FALLBACK_COLORS[index % FALLBACK_COLORS.length];
  const disposeObject = object => {
    object.traverse(child => {
      child.geometry?.dispose();
      if (child.material) (Array.isArray(child.material) ? child.material : [child.material]).forEach(item => item.dispose());
    });
    object.parent?.remove(object);
  };
  const clearStructure = () => {
    for (const child of [...field.children]) if (child !== hub) disposeObject(child);
    nodes.clear();
    packets = [];
    labels.replaceChildren?.();
  };
  const positionFor = (index, count) => {
    const phase = index * 2.39996 - 1.1;
    const y = count === 1 ? 0 : 1 - 2 * (index + 0.5) / count;
    const r = Math.sqrt(Math.max(0, 1 - y * y));
    return new THREE.Vector3(Math.cos(phase) * r * 4.15, y * 2.8, Math.sin(phase) * r * 2.7);
  };
  const makeCurve = (start, end, bend = 0.45) => {
    const middle = start.clone().lerp(end, 0.5);
    middle.z += bend;
    return new THREE.CatmullRomCurve3([start, start.clone().lerp(middle, 0.62), middle,
      middle.clone().lerp(end, 0.62), end]);
  };
  const rebuild = (agents, goals) => {
    clearStructure();
    agents.forEach((agent, index) => {
      const id = String(agent.id || index), color = chooseColor(id, index);
      const anchors={director:[0,3.25,.3],researcher:[-4.5,1.5,.6],engineer:[-4.35,-1.7,.3],reviewer:[4.5,1.5,.6],curator:[4.35,-1.7,.3],evaluator:[0,-3.3,-.5]};
      const position=anchors[id]?new THREE.Vector3(...anchors[id]):positionFor(index,agents.length);
      const body = new THREE.Group();
      body.position.copy(position);
      const nucleus = new THREE.Mesh(new THREE.IcosahedronGeometry(0.27, 1),
        new THREE.MeshPhongMaterial({color, emissive: color, emissiveIntensity: 0.55,
          transparent: true, opacity: 0.86, flatShading: true}));
      body.add(nucleus);
      body.add(sprite(color, 1.48, 0.28));
      const shell = new THREE.Mesh(new THREE.IcosahedronGeometry(0.72, 1),
        new THREE.MeshBasicMaterial({color, wireframe: true, transparent: true, opacity: 0.18}));
      body.add(shell);
      body.userData.agentId = id;
      for (let i = 0; i < 9; i++) {
        const a = i * 2.39996 + index;
        const y = 1 - 2 * (i + 0.5) / 9;
        const r = Math.sqrt(1 - y * y);
        const direction = new THREE.Vector3(Math.cos(a) * r, y, Math.sin(a) * r);
        const endpoint = direction.clone().multiplyScalar(0.91 + (i % 3) * 0.16);
        const twig = new THREE.Mesh(new THREE.TubeGeometry(
          new THREE.QuadraticBezierCurve3(direction.clone().multiplyScalar(0.17),
            direction.clone().multiplyScalar(0.52).add(new THREE.Vector3(0, 0.08, 0)), endpoint),
          9, 0.006, 3, false), material(color, 0.23));
        body.add(twig);
        const tip = sprite(color, 0.12, 0.5); tip.position.copy(endpoint); body.add(tip);
      }
      field.add(body);
      const tag=document.createElement('span');tag.className='core-space-label';tag.textContent=agent.name||id;tag.style.color='#'+new THREE.Color(color).getHexString();labels.append(tag);
      const origin = center.clone().multiplyScalar(1.04);
      const curve = makeCurve(origin, position, 0.5 + (index % 2) * 0.25);
      line(curve, color, 0.12, 0.013);
      line(curve, color, 0.035, 0.055);
      nodes.set(id, {position, color, body, nucleus, shell, curve,tag});
    });
    // These branches exist only when the backend has stored a delegation goal.
    roleEdges(goals, [...nodes.keys()]).forEach(({parent, child}) => {
      const curve = makeCurve(nodes.get(parent).position, nodes.get(child).position, -0.65);
      line(curve, 0xb8c9cf, 0.12, 0.007);
    });
    highlight();
    renderOnce();
  };
  const highlight = () => {
    nodes.forEach((node, id) => {
      const chosen = selected === id;
      node.shell.material.opacity = chosen ? 0.56 : 0.18;
      node.body.scale.setScalar(chosen ? 1.1 : 1);
    });
  };
  const addPacket = (node, curve) => {
    if (prefersReducedMotion() || !visible || !node) return;
    const mesh = sprite(node.color, 0.24, 0.95);
    field.add(mesh);
    packets.push({mesh, curve, start: performance.now(), duration: 1300});
    while (packets.length > MAX_PACKETS) disposeObject(packets.shift().mesh);
    requestFrame();
  };
  const processEvents = (events, goals) => {
    const result = nextEventPackets(seenEvents, events, {baseline: baselineSet, visible});
    result.fresh.filter(event => event.kind !== 'delegate').forEach(event => {
      const node = nodes.get(String(event.role));
      if (node) addPacket(node, node.curve);
    });
    const delegations = nextDelegations(seenGoals, goals, {baseline: baselineSet, visible});
    delegations.fresh.forEach(goal => {
      const parent = nodes.get(String(goal.parent)), child = nodes.get(String(goal.agent));
      if (parent && child) addPacket(child, makeCurve(parent.position, child.position, -0.65));
    });
    seenEvents = result.seen;
    seenGoals = delegations.seen;
    baselineSet = true;
  };
  const renderOnce = () => {
    if (!destroyed && visible && !contextLost && canvasHost.clientWidth && canvasHost.clientHeight) {
      if(composer)composer.render();else renderer.render(scene,camera);
      nodes.forEach(node=>{const p=node.body.getWorldPosition(new THREE.Vector3()).project(camera);node.tag.style.transform=`translate(-50%,-50%) translate(${(p.x*.5+.5)*canvasHost.clientWidth}px,${(-p.y*.5+.5)*canvasHost.clientHeight+37}px)`;});
    }
  };
  const tick = now => {
    frame = 0;
    if (destroyed || !visible || contextLost) return;
    if (now - lastFrame < FRAME_MS) { requestFrame(); return; }
    lastFrame = now;
    const reduced = prefersReducedMotion();
    horizon.update(now/1000,reduced);
    packets = packets.filter(packet => {
      // RAF timestamps can precede a receipt captured later in that same frame.
      const progress = Math.max(0, (now - packet.start) / packet.duration);
      if (progress >= 1 || reduced) { disposeObject(packet.mesh); return false; }
      packet.mesh.position.copy(packet.curve.getPoint(progress));
      packet.mesh.material.opacity = Math.min(1, (1 - progress) * 1.6);
      return true;
    });
    renderOnce();
    if (!reduced || packets.length) requestFrame();
  };
  const requestFrame = () => { if (!frame && visible && !destroyed && !contextLost) frame = requestAnimationFrame(tick); };
  const resize = () => {
    const width = Math.max(1, canvasHost.clientWidth), height = Math.max(1, canvasHost.clientHeight);
    renderer.setSize(width, height, false);
    composer?.setSize(width,height);
    camera.aspect = width / height;
    const halfFov = THREE.MathUtils.degToRad(camera.fov / 2);
    camera.position.z = Math.max(13.7, 2.7 + 5.5 / (Math.tan(halfFov) * camera.aspect))*zoom;
    camera.lookAt(0, 0, 0);
    camera.updateProjectionMatrix();
    renderOnce();
  };
  const resizeObserver = new ResizeObserver(resize);
  resizeObserver.observe(canvasHost);
  const intersectionObserver = new IntersectionObserver(entries => {
    inViewport = entries[0]?.isIntersecting === true;
    visible = inViewport && !document.hidden;
    if (visible) requestFrame(); else if (frame) { cancelAnimationFrame(frame); frame = 0; }
  });
  intersectionObserver.observe(canvasHost);
  const pick = event => {
    const rect = renderer.domElement.getBoundingClientRect();
    if (!rect.width || !rect.height) return '';
    pointer.set((event.clientX - rect.left) / rect.width * 2 - 1,
      -(event.clientY - rect.top) / rect.height * 2 + 1);
    raycaster.setFromCamera(pointer, camera);
    const targets = [...nodes.values()].flatMap(node => [node.nucleus, node.shell]);
    for (const hit of raycaster.intersectObjects(targets, false)) {
      const id = hit.object.parent?.userData.agentId;
      if (id) return id;
    }
    return '';
  };
  const onPointerMove = event => {
    if(drag){const dx=event.clientX-drag.x,dy=event.clientY-drag.y;if(Math.abs(dx)+Math.abs(dy)>3)dragged=true;field.rotation.y=Math.max(-.65,Math.min(.65,drag.ry+dx*.003));field.rotation.x=Math.max(-.3,Math.min(.3,drag.rx+dy*.002));renderOnce();return;}
    renderer.domElement.style.cursor = pick(event) ? 'pointer' : 'grab';
  };
  const onClick = event => {if(dragged){dragged=false;return;}const id = pick(event); if (id) onSelect(id); };
  const onDown=event=>{dragged=false;drag={x:event.clientX,y:event.clientY,rx:field.rotation.x,ry:field.rotation.y};renderer.domElement.setPointerCapture?.(event.pointerId);};
  const onUp=()=>{drag=null;};
  const onReset=()=>{field.rotation.set(0,0,0);zoom=1;resize();};
  renderer.domElement.addEventListener('pointerdown',onDown);
  renderer.domElement.addEventListener('pointerup',onUp);
  renderer.domElement.addEventListener('pointercancel',onUp);
  renderer.domElement.addEventListener('dblclick',onReset);
  const onVisibility = () => {
    visible = inViewport && !document.hidden;
    if (visible) requestFrame(); else if (frame) { cancelAnimationFrame(frame); frame = 0; }
  };
  const onLost = event => { event.preventDefault(); contextLost = true; if (frame) cancelAnimationFrame(frame); frame = 0; onStatus('paused'); };
  const onRestored = () => { contextLost = false; resize(); requestFrame(); onStatus('ready'); };
  document.addEventListener('visibilitychange', onVisibility);
  renderer.domElement.addEventListener('webglcontextlost', onLost);
  renderer.domElement.addEventListener('webglcontextrestored', onRestored);
  renderer.domElement.addEventListener('pointermove', onPointerMove);
  renderer.domElement.addEventListener('click', onClick);
  motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
  const onMotion = () => { if (motionQuery.matches) field.rotation.y = 0; renderOnce(); requestFrame(); };
  motionQuery.addEventListener?.('change', onMotion);
  resize(); requestFrame();
  return {
    update(snapshot, selection) {
      if (destroyed) return;
      selected = selection || '';
      const agents = list(snapshot?.agents);
      const goals = list(snapshot?.goals);
      const next = JSON.stringify([agents.map(agent => agent.id), goals.map(goal => [goal.parent, goal.agent])]);
      if (next !== topology) { topology = next; rebuild(agents, goals); }
      else { highlight(); renderOnce(); }
      const operational = rolesOperational(snapshot);
      nodes.forEach((node, id) => {
        const agent = agents.find(item => String(item.id) === id);
        const working = operational && agent && ['working', 'thinking', 'using_tool'].includes(agent.status);
        node.nucleus.material.opacity = working ? 1 : 0.72;
        node.nucleus.material.emissiveIntensity = working ? 0.85 : 0.42;
      });
      renderOnce();
      processEvents(list(snapshot?.work_receipts), goals);
    },
    setSelected(id) { selected = id || ''; highlight(); renderOnce(); },
    resetCamera:onReset,
    zoom(delta){zoom=Math.max(.8,Math.min(1.6,zoom+delta));resize();},
    dispose() {
      if (destroyed) return;
      destroyed = true;
      if (frame) cancelAnimationFrame(frame);
      resizeObserver.disconnect(); intersectionObserver.disconnect();
      document.removeEventListener('visibilitychange', onVisibility);
      motionQuery.removeEventListener?.('change', onMotion);
      renderer.domElement.removeEventListener('webglcontextlost', onLost);
      renderer.domElement.removeEventListener('webglcontextrestored', onRestored);
      renderer.domElement.removeEventListener('pointermove', onPointerMove);
      renderer.domElement.removeEventListener('click', onClick);
      renderer.domElement.removeEventListener('pointerdown',onDown);renderer.domElement.removeEventListener('pointerup',onUp);renderer.domElement.removeEventListener('pointercancel',onUp);renderer.domElement.removeEventListener('dblclick',onReset);
      clearStructure(); disposeObject(hub); glowTexture.dispose();
      composer?.passes.forEach(pass=>pass.dispose?.());composer?.dispose();renderer.dispose(); canvasHost.remove();
    },
  };
}
