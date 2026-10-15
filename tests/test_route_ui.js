const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const WEB = path.resolve(__dirname, '../web');

/* Loads every web script with the real request(); `reply(path)` answers fetch and may return a promise. */
function appHarness(reply) {
  const els = {}, intervals = [];
  const el = sel => ({sel, innerHTML:'', textContent:'', hidden:false, disabled:false, value:'', dataset:{}, style:{},
    classList:{toggle(){}, add(){}, remove(){}, contains(){ return false; }}, setAttribute(){}, removeAttribute(){}, addEventListener(){},
    focus(){}, querySelector(){ return null; }, querySelectorAll(){ return []; }, append(){}, isConnected:true, scrollIntoView(){}});
  const ctx = {console, setTimeout, clearTimeout, URL, URLSearchParams, AbortController, Promise, Date, JSON, Math,
    setInterval:(fn, ms) => intervals.push({fn, ms}), clearInterval:id => { if (intervals[id - 1]) intervals[id - 1].cleared = true; },
    localStorage:{getItem(){ return null; }, setItem(){}, removeItem(){}},
    location:{hash:'#/dashboard', pathname:'/', search:''},
    window:{addEventListener(){}, removeEventListener(){}},
    document:{body:{classList:{toggle(){}, contains(){ return false; }}, append(){}}, documentElement:{setAttribute(){}, removeAttribute(){}},
      querySelector:s => els[s] ||= el(s), querySelectorAll:() => [], getElementById:id => els['#' + id] ||= el('#' + id),
      createElement:() => el('x'), addEventListener(){}, activeElement:null, hidden:false},
    fetch:(p, {signal, method}) => new Promise((resolve, reject) => {
      ctx.fetchLog.push(`${method} ${p}`);
      signal.addEventListener('abort', () => { const e = new Error('aborted'); e.name = 'AbortError'; reject(e); });
      Promise.resolve(reply(p, method)).then(data => resolve(data === 401 ? {status:401, json:async () => ({ok:false, error:{code:'unauthorized'}})} : {status:200, json:async () => ({ok:true, data})}));
    })};
  ctx.fetchLog = [];
  ctx.history = {replaceState(_, __, url){ ctx.location.hash = url.slice(url.indexOf('#')); }};
  vm.createContext(ctx);
  for (const f of ['core.js', 'settings-ui.js', 'widgets.js', 'charts.js', 'status.js']) vm.runInContext(fs.readFileSync(path.join(WEB, f), 'utf8'), ctx, {filename:f});
  vm.runInContext(fs.readFileSync(path.join(WEB, 'app.js'), 'utf8').replace(/\nboot\(\)\.catch[^\n]*\n?$/, '\n'), ctx, {filename:'app.js'});
  vm.runInContext("session.token = 'synthetic'; session.onUnauthorized = () => showTokenForm('That access token was not accepted.');", ctx);
  return {ctx, els, content:() => (els['#content'] ||= el('#content')).innerHTML, live:() => intervals.filter(i => !i.cleared)};
}
const tick = () => new Promise(resolve => setTimeout(resolve, 5));
const OVERVIEW = {playback:{active:false}, generated_at:1760000000};
const PIPE = {summary:{health:{}, primary_player:{}, scraper_module:{}}, nodes:[], routing:{}, edges:[], settings_groups:[], discovery:{}};

test('a slow page that answers after the user left never replaces the current page', async () => {
  let release;
  const slow = new Promise(resolve => { release = resolve; });
  const {ctx, content} = appHarness(p => p === '/api/pipeline' ? slow.then(() => PIPE) : p === '/api/backups/timeline' ? {items:[]} : p === '/api/addons' ? [] : {write_enabled:true, stack:{}});
  ctx.location.hash = '#/pipeline';
  const first = ctx.route();
  await tick();
  ctx.location.hash = '#/backups';
  await ctx.route();
  assert.match(content(), /<h2>Backups<\/h2>/);
  release();
  await first;
  await tick();
  assert.match(content(), /<h2>Backups<\/h2>/);
  assert.doesNotMatch(content(), /Couldn’t load this page/);
});

test('unknown pages and #/ open the overview under #/dashboard instead of a stuck skeleton', async () => {
  for (const hash of ['#/no-such-page', '#/', '#/dashboard?x=1']) {
    const {ctx, content} = appHarness(p => p === '/api/overview' ? OVERVIEW : p.startsWith('/api/status') ? {write_enabled:true, stack:{}} : null);
    ctx.location.hash = hash;
    await ctx.route();
    assert.equal(ctx.location.hash, '#/dashboard', hash);
    assert.doesNotMatch(content(), /Checking your Kodi/, hash);
    assert.match(content(), /Overview/, hash);
  }
});

for (const [page, marker] of [['#/dashboard', /Overview/], ['#/components', /Your add-ons/]]) {
  test(`after a rejected token on ${page}, no refresh timer re-renders the token form`, async () => {
    let rejected = false;
    const {ctx, content, live} = appHarness(p => rejected ? 401 : p === '/api/overview' ? OVERVIEW : p === '/api/addons' ? [] : {write_enabled:true, stack:{}});
    ctx.location.hash = page;
    await ctx.route();
    assert.match(content(), marker);
    assert.equal(live().length, 1);
    rejected = true;
    await live()[0].fn();
    await tick();
    assert.match(content(), /Connect to Kodi Manager/);
    assert.equal(live().length, 0, 'no polling timer stays armed behind the token form');
  });
}

/* Write handlers: the user may leave the page while Kodi is still answering. */
function recordToasts(ctx){ const toasts = []; ctx.toast = (message, tone) => { toasts.push({message, tone}); return null; }; return toasts; }
const PAGES = p => p === '/api/backups/timeline' ? {items:[]} : p === '/api/addons' ? [] : p === '/api/logs' ? {lines:['hello']} : {write_enabled:true, stack:{}};

test('a write that finishes after the user left reports its outcome and leaves the new page alone', async () => {
  let release;
  const slow = new Promise(resolve => { release = resolve; });
  const {ctx, els, content} = appHarness((p, method) => method === 'POST' && p === '/api/stack/backup' ? slow.then(() => ({backup_id:'cp-1'})) : PAGES(p));
  const toasts = recordToasts(ctx);
  ctx.location.hash = '#/backups';
  await ctx.route();
  const click = els['#stackBackup'].onclick({currentTarget:null});
  await tick();
  ctx.location.hash = '#/logs';
  await ctx.route();
  assert.match(content(), /Service log/);
  const reads = ctx.fetchLog.length;
  release();
  await click;
  await tick();
  assert.match(content(), /Service log/, 'the Backups page is not drawn over the Service log');
  assert.doesNotMatch(content(), /<h2>Backups<\/h2>/);
  assert.deepEqual(ctx.fetchLog.slice(reads), [], 'no reload of the old page is requested');
  assert.deepEqual(toasts.map(t => t.message), ['Checkpoint cp-1 created.']);
});

test('a write on the same page still redraws it', async () => {
  const {ctx, els, content} = appHarness((p, method) => method === 'POST' ? {backup_id:'cp-2'} : PAGES(p));
  recordToasts(ctx);
  ctx.location.hash = '#/backups';
  await ctx.route();
  const before = ctx.fetchLog.filter(line => line === 'GET /api/backups/timeline').length;
  await els['#stackBackup'].onclick({currentTarget:null});
  assert.equal(ctx.fetchLog.filter(line => line === 'GET /api/backups/timeline').length, before + 1);
  assert.match(content(), /<h2>Backups<\/h2>/);
});

for (const [page, button, endpoint, reply, expected] of [
  ['#/install', '#installZip', '/api/addons/install', {opened:true, next_step:'Choose the ZIP on the TV.'}, /^Choose the ZIP on the TV\.$/],
  ['#/playback-test', '#runPlaybackTest', '/api/playback/test', {steps:[{step:'Routing', ok:true}, {step:'Player', ok:false}]}, /^Playback test finished: 1 of 2 checks passed/],
  ['#/fixes', '#restoreFixes', '/api/fixes/repair', {detail:'2 files restored.'}, /^2 files restored\.$/]]) {
  test(`a result from ${button} after leaving ${page} becomes a toast, not a TypeError`, async () => {
    let release;
    const slow = new Promise(resolve => { release = resolve; });
    const {ctx, els, content} = appHarness((p, method) => method === 'POST' && p === endpoint ? slow.then(() => reply)
      : p === '/api/pipeline' ? {...PIPE, summary:{...PIPE.summary, primary_player:{addon_id:'plugin.video.pov'}}} : p === '/api/fixes' ? {bundled:true, groups:[], repairable:true, detail:'d'} : PAGES(p));
    const toasts = recordToasts(ctx);
    ctx.confirmDialog = async () => true;
    ctx.location.hash = page;
    await ctx.route();
    const click = els[button].onclick({currentTarget:null});
    await tick();
    ctx.location.hash = '#/logs';
    await ctx.route();
    // The old page's elements are gone once the new page is drawn.
    const gone = ['#playbackSteps', '#playbackOut', '#installOut', '#fixResult'], find = ctx.document.querySelector;
    ctx.document.querySelector = s => gone.includes(s) ? null : find(s);
    release();
    await click;
    await tick();
    assert.match(content(), /Service log/);
    assert.equal(toasts.length, 1, JSON.stringify(toasts));
    assert.match(toasts[0].message, expected);
    assert.notEqual(toasts[0].tone, 'error');
  });
}

/* TV remotes: arrows the focused control does not use must move focus. */
test('arrow keys leave charts, number fields, sliders and selects in the directions they do not use', () => {
  const {ctx} = appHarness(() => ({}));
  const rect = (left, top, width, height) => ({left, top, right:left + width, bottom:top + height, width, height});
  const make = (name, r, extra = {}) => ({name, tagName:'DIV', type:'', getClientRects:() => [1], getBoundingClientRect:() => r, closest:() => null, focus(){ ctx.focused = name; }, scrollIntoView(){}, ...extra});
  const neighbours = [make('above', rect(300, 0, 100, 30)), make('below', rect(300, 400, 100, 30)), make('left', rect(0, 200, 100, 30)), make('right', rect(600, 200, 100, 30))];
  const at = rect(300, 200, 100, 30);
  const controls = {
    chart:make('chart', at, {closest:s => s === '[data-chart-plot]' ? {} : null}),
    number:make('number', at, {tagName:'INPUT', type:'number'}),
    range:make('range', at, {tagName:'INPUT', type:'range'}),
    select:make('select', at, {tagName:'SELECT'}),
    text:make('text', at, {tagName:'INPUT', type:'text'}),
    checkbox:make('checkbox', at, {tagName:'INPUT', type:'checkbox'}),
    textarea:make('textarea', at, {tagName:'TEXTAREA'}),
    button:make('button', at, {tagName:'BUTTON'})};
  // Directions each control keeps for itself; every other arrow moves focus.
  const keeps = {chart:['left', 'right'], number:['up', 'down'], range:['left', 'right'], select:['up', 'down'], text:['left', 'right'], checkbox:[], textarea:['up', 'down', 'left', 'right'], button:[]};
  ctx.document.querySelector = () => null;
  for (const [name, active] of Object.entries(controls)) {
    for (const [key, dir] of [['ArrowUp', 'up'], ['ArrowDown', 'down'], ['ArrowLeft', 'left'], ['ArrowRight', 'right']]) {
      ctx.focused = null;
      ctx.document.activeElement = active;
      ctx.document.querySelectorAll = () => [...neighbours, active];
      let prevented = false;
      ctx.spatialKey({key, defaultPrevented:false, preventDefault(){ prevented = true; }});
      const kept = keeps[name].includes(dir);
      assert.equal(ctx.focused, kept ? null : (dir === 'up' ? 'above' : dir === 'down' ? 'below' : dir), `${name} ${key}`);
      assert.equal(prevented, !kept, `${name} ${key} default`);
    }
  }
});

/* The add-ons page refreshes every 30 seconds; focus must stay on the same control. */
test('a components refresh puts focus back on a row link, the table or the notices', async () => {
  for (const key of ['row:skin', 'table', 'notices']) {
    const {ctx, els, content, live} = appHarness(p => p === '/api/addons' ? [] : p === '/api/status' ? {write_enabled:true, stack:{warnings:['w']}, active_skin:{addon_id:'skin.example'}} : null);
    ctx.location.hash = '#/components';
    await ctx.route();
    assert.match(content(), new RegExp(`data-dash-focus="${key}"`), key);
    let focused = 0;
    const selector = `[data-dash-focus="${key}"]`;
    els[selector] = {focus(){ focused++; }};
    ctx.document.activeElement = {dataset:{dashFocus:key}};
    await live()[0].fn();
    await tick();
    assert.equal(focused, 1, key);
  }
});

test('the Trends page shows the range pressed last even when an earlier range answers later', async () => {
  let releaseWeek;
  const week = new Promise(resolve => { releaseWeek = resolve; });
  const history = days => ({count:0, series:{t:[]}, days});
  const {ctx, content} = appHarness(p => p === '/api/metrics/history?days=7' ? week.then(() => history(7)) : p.startsWith('/api/metrics/history') ? history(1) : PAGES(p));
  ctx.location.hash = '#/trends';
  const first = ctx.route();
  await tick();
  await ctx.trendsView(1);
  assert.match(content(), /data-range="1" aria-pressed="true"/);
  releaseWeek();
  await first;
  await tick();
  assert.match(content(), /data-range="1" aria-pressed="true"/, 'the slower 7-day answer does not replace the 24-hour view');
});
