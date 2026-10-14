// Run the actual inline controllers against controlled browser and network events.
const fs = require('fs'), path = require('path'), vm = require('vm'), assert = require('assert/strict');
const html = fs.readFileSync(path.join(__dirname, '../clipbot/dashboard/static/index.html'), 'utf8');
const elements = new Map();
function element(id) {
  if (!elements.has(id)) {
    const classes = new Set(id === '#wVideo' ? ['on'] : []), listeners = {};
    elements.set(id, {dataset: {}, hidden: false, disabled: false, value: '0.6', paused: true, src: '', textContent: '', innerHTML: '', buffered: {length: 0},
      classList: {add: x => classes.add(x), remove: x => classes.delete(x), contains: x => classes.has(x), toggle(x, on) { if (on) classes.add(x); else classes.delete(x); }},
      addEventListener(name, fn) { listeners[name] = fn; }, removeEventListener(name) { delete listeners[name]; }, listeners,
      removeAttribute(name) { this[name] = ''; }, load() {}, pause() { this.paused = true; }, play() { this.paused = false; return Promise.resolve(); }});
  }
  return elements.get(id);
}
let serial = 0;
class MediaSource {
  static isTypeSupported() { return true; }
  constructor() { this.readyState = 'open'; this.listeners = {}; this.added = 0; }
  addEventListener(name, fn) { this.listeners[name] = fn; }
  addSourceBuffer() { this.added++; return {updating: false, buffered: {length: 0}, addEventListener() {}, appendBuffer() {}}; }
  endOfStream() {}
}
const timers = new Map();
const sandbox = {$: element, $$: () => [], console, MediaSource, AbortController, document: {addEventListener() {}, fullscreenElement: null},
  window: {MediaSource, open() {}}, URL: {createObjectURL: () => 'blob:' + ++serial, revokeObjectURL() {}},
  setTimeout: fn => { const id = ++serial; timers.set(id, fn); return id; }, clearTimeout: id => timers.delete(id),
  state: null, sfx() {}, toast() {}, esc: String, poll() {}, renderBusinessReadiness() {},
  api: () => new Promise(() => {}), fetch: () => new Promise(() => {}), assert, elements, timers};
vm.createContext(sandbox);
const tune = html.slice(html.indexOf('/* system: auto-tune + storage */'), html.indexOf('function fmtBytes'));
const live = html.slice(html.indexOf('/* ---------------- live viewer:'), html.indexOf('/* ---------------- system panel'));
vm.runInContext(tune + '\n' + live, sandbox);
(async () => {
  await vm.runInContext(`(async () => {
    window.MediaSource = null;
    await openWatch('same'); W.queue = ['seg_20261013120000']; wNext();
    const previous = $('#wVideo').src; assert(previous.includes('seg_20261013120000'));
    await openWatch('same'); W.queue = ['seg_20261013120000']; wNext();
    assert.equal($('#wVideo').src, previous, 'reopening restores removed src even for same segment');
    assert.equal(W.lastName, null);

    window.MediaSource = MediaSource; await openWatch('same'); const old = W.ms;
    await openWatch('same'); const current = W.ms;
    old.listeners.sourceopen(); assert.equal(old.added, 0, 'stale sourceopen must not mutate new viewer');
    current.listeners.sourceopen(); assert.equal(current.added, 1);
    W.info = {platform: 'kick', login: 'fixture'};
    const source = $('#wVideo').src;
    $('#wMode').listeners.click(); assert(W.official);
    $('#wMode').listeners.click(); assert(!W.official);
    assert.equal($('#wVideo').src, source, 'return from official player preserves active MediaSource');

    let resolveOld;
    fetch = () => new Promise(resolve => { resolveOld = resolve; });
    W.queue = ['seg_20261013120000']; const pending = wFetch();
    await openWatch('same'); W.fetching = true;
    resolveOld({ok: true, arrayBuffer: async () => new ArrayBuffer(1)}); await pending;
    assert.equal(W.pending.length, 0, 'old same-key fetch must not append into replacement viewer');
    assert.equal(W.fetching, true, 'old finally must not clear replacement fetch state');

    api = async () => { throw new Error('offline'); };
    await wTick(); assert($('#wMeta').textContent.includes('retrying'));
    assert(W.timer !== null, 'network failure must schedule the next live refresh');
    await $('#scanBtn').listeners.click();
    assert.equal($('#scanBtn').disabled, false); assert(!$('#scanBtn').classList.contains('busy'));
    assert($('#hwBox').textContent.includes('retry'));
    recs = [{field: 'edit.encoder', value: 'h264_nvenc'}];
    $$ = () => [{dataset: {i: '0'}}];
    await $('#applyRecs').listeners.click();
    assert.equal($('#applyRecs').disabled, false); assert($('#recMsg').textContent.includes('Retry'));
    wStop();
  })()`, sandbox);
  process.stdout.write('Live/tune controller lifecycle checks passed.\n');
})().catch(error => { console.error(error); process.exitCode = 1; });
