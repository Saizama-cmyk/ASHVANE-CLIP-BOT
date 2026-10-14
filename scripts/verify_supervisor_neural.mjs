import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';

const root = new URL('../clipbot/dashboard/static/', import.meta.url);
const pureSource = readFileSync(new URL('supervisor-topology.js', root), 'utf8');
const {roleEdges, rolesOperational, nextEventPackets, nextDelegations} = await import(
  'data:text/javascript;base64,' + Buffer.from(pureSource).toString('base64'));
const roles = ['director', 'researcher', 'engineer', 'reviewer', 'curator', 'evaluator'];

assert.deepEqual(roleEdges([], roles), []);
assert.deepEqual(roleEdges([
  {parent: 'director', agent: 'engineer', goal: 'Check a repair'},
  {parent: 'director', agent: 'engineer', goal: 'Another repair'},
  {parent: 'engineer', agent: 'reviewer', goal: 'Review'},
  {parent: 'director', agent: 'invented', goal: 'Unknown'},
], roles), [
  {parent: 'director', child: 'engineer'},
  {parent: 'engineer', child: 'reviewer'},
]);

const waiting = {enabled: true, state: 'waiting_for_business', agents: roles.map(id => ({id, status: 'thinking'}))};
assert.equal(rolesOperational(waiting), false, 'deferred work must keep even stale thinking agents quiet');
assert.equal(rolesOperational({...waiting, state: 'investigating'}), true);
assert.equal(rolesOperational({...waiting, enabled: false, state: 'investigating'}), false);

const previousEvent = {id: 'historical', role: 'director', kind: 'deferred', at: 90};
const currentEvent = {id: 'new-real', role: 'reviewer', kind: 'review', at: 100};
const first = nextEventPackets(new Set(), [previousEvent], {baseline: false, visible: true, now: 100});
assert.equal(first.fresh.length, 0, 'the initial ledger is history, never animation');
const next = nextEventPackets(first.seen, [previousEvent, currentEvent], {baseline: true, visible: true, now: 101});
assert.deepEqual(next.fresh.map(event => event.id), ['new-real']);
assert.equal(nextEventPackets(next.seen, [previousEvent, currentEvent], {baseline: true, visible: true, now: 102}).fresh.length, 0);
assert.equal(nextEventPackets(first.seen, [previousEvent, currentEvent], {baseline: true, visible: false, now: 101}).fresh.length, 0);
assert.equal(nextEventPackets(first.seen, [previousEvent, {...currentEvent, at: 70}], {baseline: true, visible: true, now: 101}).fresh.length, 0);
assert.equal(nextEventPackets(first.seen, [previousEvent, {...currentEvent, role: null}], {baseline: true, visible: true, now: 101}).fresh.length, 0);

const recordedGoal = {id: 'recorded-goal', parent: 'director', agent: 'engineer', created_at: 100};
const olderGoal = {id: 'old-goal', parent: 'director', agent: 'curator', created_at: 90};
const initialGoals = nextDelegations(new Set(), [olderGoal], {baseline: false, visible: true, now: 100});
assert.equal(initialGoals.fresh.length, 0);
assert.deepEqual(nextDelegations(initialGoals.seen, [olderGoal, recordedGoal], {baseline: true, visible: true, now: 101}).fresh.map(goal => goal.id), ['recorded-goal']);
assert.equal(nextDelegations(initialGoals.seen, [olderGoal, recordedGoal], {baseline: true, visible: false, now: 101}).fresh.length, 0);

const visualSource = readFileSync(new URL('supervisor-neural.js', root), 'utf8');
for (const required of ['MAX_PIXEL_RATIO = 1.5', 'FRAME_MS = 1000 / 30', 'ResizeObserver', 'IntersectionObserver', 'webglcontextlost', 'dispose()', 'prefers-reduced-motion', 'camera.position.z = Math.max', "event.kind !== 'delegate'", 'inViewport && !document.hidden']) {
  assert.ok(visualSource.includes(required), `missing renderer lifecycle guard: ${required}`);
}
assert.ok(visualSource.includes("./vendor/three/0.186.1/build/three.module.js"));
const hash16 = bytes => createHash('sha256').update(bytes).digest('hex').slice(0, 16);
const controllerSource = readFileSync(new URL('supervisor.js', root), 'utf8');
assert.ok(controllerSource.includes(`/static/supervisor-neural.js?v=${hash16(visualSource)}`));
assert.ok(visualSource.includes(`./supervisor-topology.js?v=${hash16(pureSource)}`));
assert.equal(createHash('sha256').update(readFileSync(new URL('vendor/three/0.186.1/build/three.module.js', root))).digest('hex').toUpperCase(),
  '9052042D676CB0FDC1DDFEFE193053F34B7AC0513A616FDAC4535D49987812EA');
assert.equal(createHash('sha256').update(readFileSync(new URL('vendor/three/0.186.1/build/three.core.js', root))).digest('hex').toUpperCase(),
  '9EDDE002B066A9A05676A6127F67735B62BAF399BDEA529F2F7E31657DA769E6');
assert.ok(readFileSync(new URL('vendor/three/0.186.1/LICENSE', root), 'utf8').includes('MIT License'));
console.log('Supervisor neural topology, real-event gate and renderer lifecycle guards: passed');
