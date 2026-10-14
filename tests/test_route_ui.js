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
    fetch:(p, {signal}) => new Promise((resolve, reject) => {
      signal.addEventListener('abort', () => { const e = new Error('aborted'); e.name = 'AbortError'; reject(e); });
      Promise.resolve(reply(p)).then(data => resolve(data === 401 ? {status:401, json:async () => ({ok:false, error:{code:'unauthorized'}})} : {status:200, json:async () => ({ok:true, data})}));
    })};
  ctx.history = {replaceState(_, __, url){ ctx.location.hash = url.slice(url.indexOf('#')); }};
  vm.createContext(ctx);
  for (const f of ['core.js', 'settings-ui.js', 'widgets.js', 'charts.js', 'status.js']) vm.runInContext(fs.readFileSync(path.join(WEB, f), 'utf8'), ctx, {filename:f});
  vm.runInContext(fs.readFileSync(path.join(WEB, 'app.js'), 'utf8').replace(/\nboot\(\)\.catch[^\n]*\n?$/, '\n'), ctx, {filename:'app.js'});
  vm.runInContext("session.token = 'synthetic'; session.onUnauthorized = () => showTokenForm('That access token was not accepted.');", ctx);
  return {ctx, content:() => (els['#content'] ||= el('#content')).innerHTML, live:() => intervals.filter(i => !i.cleared)};
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
