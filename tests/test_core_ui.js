const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const web = name => fs.readFileSync(path.resolve(__dirname, '../web', name), 'utf8');
const core = web('core.js');
const app = web('app.js').replace(/boot\(\)\.catch[^\n]+;\s*$/, '');

function context(extra = {}) {
  const storage = new Map();
  const ui = {console:{error(){}}, setTimeout, clearTimeout, setInterval, clearInterval, URLSearchParams, AbortController,
    localStorage:{getItem:key => storage.get(key) ?? null, setItem:(key, value) => storage.set(key, value), removeItem:key => storage.delete(key)},
    ...extra};
  vm.createContext(ui);
  vm.runInContext(core, ui);
  return {ui, storage};
}
function withApp(extra = {}) {
  const harness = context(extra);
  vm.runInContext(app, harness.ui);
  return harness;
}
const response = (status, body, json = true) => ({status, json:async () => { if (!json) throw new SyntaxError('Unexpected token <'); return body; }});

test('escape helper covers every HTML-significant character', () => {
  const {ui} = context();
  ui.esc = vm.runInContext('esc', ui);
  assert.equal(ui.esc(`<a href="x" onclick='y'>&\``), '&lt;a href=&quot;x&quot; onclick=&#39;y&#39;&gt;&amp;&#96;');
  assert.equal(ui.esc(null), '');
  assert.equal(ui.esc(0), '0');
});

test('tokens are accepted only from the URL fragment', () => {
  const {ui} = context();
  assert.equal(ui.tokenFromHash('#token=abc%2Fdef'), 'abc/def');
  assert.equal(ui.tokenFromHash('#/dashboard'), '');
  assert.equal(ui.tokenFromHash('?token=abc'), '');
  assert.equal(ui.tokenFromHash('#token=%E0%A4%A'), '');
  assert.equal(ui.dashboardLink('http://192.168.1.20:8765/', 'a b'), 'http://192.168.1.20:8765/#token=a%20b');
});

test('consumeUrlToken stores a fragment token, strips it from history and ignores query tokens', () => {
  const replaced = [];
  const location = {hash:'#token=secret', pathname:'/', search:''};
  const {ui, storage} = withApp({location, history:{replaceState:(_, __, url) => replaced.push(url)}});
  assert.equal(ui.consumeUrlToken(), true);
  assert.equal(storage.get('bsa_token'), 'secret');
  assert.deepEqual(replaced, ['/#/dashboard']);
  location.hash = '#/dashboard';
  location.search = '?token=other';
  assert.equal(ui.consumeUrlToken(), false);
  assert.equal(storage.get('bsa_token'), 'secret');
});

test('api reports network failures, non-JSON replies and error codes clearly', async () => {
  const {ui} = context({fetch:async () => { throw new TypeError('Failed to fetch'); }});
  await assert.rejects(ui.api('/api/status'), error => error.code === 'network' && /Couldn’t reach Kodi Manager/.test(error.message));
  ui.fetch = async () => response(502, null, false);
  await assert.rejects(ui.api('/api/status'), error => error.code === 'bad_response' && /HTTP 502/.test(error.message));
  ui.fetch = async () => response(409, {ok:false, error:{code:'playback_active', message:'Stop playback before restoring a backup'}});
  await assert.rejects(ui.api('/api/stack/restore', {backup_id:'x'}), error => error.status === 409 && error.code === 'playback_active');
  ui.fetch = async () => response(200, {ok:true, data:{fine:true}});
  assert.equal((await ui.api('/api/status')).fine, true);
});

test('api clears a rejected token and asks for a new one', async () => {
  const sent = [];
  const {ui, storage} = context({fetch:async (url, options) => { sent.push(options.headers.Authorization); return response(401, {ok:false, error:{code:'unauthorized', message:'Missing or invalid bearer token'}}); }});
  ui.storeToken('old');
  vm.runInContext('session.onUnauthorized = () => { globalThis.asked = (globalThis.asked || 0) + 1; }', ui);
  await assert.rejects(ui.api('/api/status'), error => error.code === 'unauthorized');
  assert.deepEqual(sent, ['Bearer old']);
  assert.equal(storage.has('bsa_token'), false);
  assert.equal(vm.runInContext('session.token', ui), '');
  assert.equal(ui.asked, 1);
});

test('a delayed rejection of an old token preserves the new sign-in', async () => {
  let reply;
  const {ui, storage} = context({fetch:() => new Promise(resolve => { reply = resolve; })});
  ui.storeToken('old-profile-token');
  const pending = ui.api('/api/status');
  ui.storeToken('new-profile-token');
  reply(response(401, {ok:false}));
  await assert.rejects(pending, error => error.name === 'AbortError');
  assert.equal(storage.get('bsa_token'), 'new-profile-token');
});

test('stalled headers or response bodies time out and release a busy button without retrying', async () => {
  for (const stage of ['headers', 'body']) {
    let expire, calls = 0, cleared = 0;
    const errors = [];
    const {ui, storage} = context({
      setTimeout:(fn, ms) => { assert.equal(ms, 60000); expire = fn; return 1; },
      clearTimeout:() => { cleared++; },
      console:{error:message => errors.push(message)},
      fetch:async (_, {signal}) => {
        calls++;
        const hang = () => new Promise((_, reject) => signal.addEventListener('abort', () => {
          const error = new Error('aborted'); error.name = 'AbortError'; reject(error);
        }));
        return stage === 'headers' ? hang() : {status:200, json:hang};
      }
    });
    ui.storeToken('still-valid');
    const button = {tagName:'BUTTON', disabled:false};
    const pending = ui.withErrors(() => ui.api('/api/stack/restore', {backup_id:'synthetic'}))({currentTarget:button});
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(button.disabled, true);
    expire();
    await pending;
    assert.equal(button.disabled, false);
    assert.equal(calls, 1);
    assert.equal(cleared, 1);
    assert.equal(storage.get('bsa_token'), 'still-valid');
    assert.match(errors[0], /may already have completed/);
    assert.match(errors[0], /Do not repeat the write automatically/);
  }
});

test('caller cancellation remains silent and cancels the request timeout', async () => {
  let cleared = 0;
  const controller = new AbortController();
  const {ui} = context({clearTimeout:timer => { clearTimeout(timer); cleared++; },
    fetch:(_, {signal}) => new Promise((_, reject) => signal.addEventListener('abort', () => {
      const error = new Error('aborted'); error.name = 'AbortError'; reject(error);
    }))});
  const pending = ui.api('/api/status', undefined, controller.signal);
  controller.abort();
  await assert.rejects(pending, error => error.name === 'AbortError');
  assert.equal(cleared, 1);
});

test('withErrors turns failures into a notice and keeps the button usable', async () => {
  const errors = [];
  const {ui} = context({console:{error:message => errors.push(message)}});
  const button = {tagName:'BUTTON', disabled:false};
  let seenDisabled = null;
  const handler = ui.withErrors(async () => { seenDisabled = button.disabled; throw new Error('Restore failed'); });
  assert.equal(await handler({currentTarget:button}), undefined);
  assert.equal(seenDisabled, true);
  assert.equal(button.disabled, false);
  assert.deepEqual(errors, ['Restore failed']);
  assert.equal(await ui.withErrors(async () => 'ok')(), 'ok');
  const aborted = ui.withErrors(async () => { const error = new Error('aborted'); error.name = 'AbortError'; throw error; });
  await aborted();
  assert.equal(errors.length, 1);
});

test('copyText falls back from the clipboard API to execCommand, then to manual selection', async () => {
  const appended = [];
  const document = {body:{append:node => appended.push(node)}, execCommand:() => true,
    createElement:() => ({style:{}, setAttribute(){}, select(){ this.selected = true; }, remove(){ this.removed = true; }})};
  const insecure = context({document, isSecureContext:false, navigator:{clipboard:{writeText:async () => { throw new Error('should not be used'); }}}});
  assert.equal(await insecure.ui.copyText('http://kodi:8765/#token=x'), 'execCommand');
  assert.equal(appended[0].value, 'http://kodi:8765/#token=x');
  assert.equal(appended[0].selected, true);
  assert.equal(appended[0].removed, true);
  document.execCommand = () => false;
  assert.equal(await insecure.ui.copyText('text'), 'manual');
  let copied = '';
  const secure = context({navigator:{clipboard:{writeText:async value => { copied = value; }}}});
  assert.equal(await secure.ui.copyText('report'), 'clipboard');
  assert.equal(copied, 'report');
});

test('leaving a page with unsaved settings asks first and keeps edits when declined', async () => {
  const location = {hash:'#/addons', pathname:'/', search:''};
  const history = {replaceState:(_, __, url) => { location.hash = url; }};
  const {ui} = withApp({location, history, document:{querySelector:() => null, querySelectorAll:() => []}});
  vm.runInContext('state.currentHash = "#/addon/plugin.video.pov"; state.dirtyChanges = {enabled:{value:"false"}}; state.dirtyAddon = "plugin.video.pov";', ui);
  ui.confirmDialog = async () => false;
  assert.equal(await ui.confirmLeave('#/addons'), false);
  assert.equal(location.hash, '#/addon/plugin.video.pov');
  assert.equal(vm.runInContext('state.dirtyChanges.enabled.value', ui), 'false');
  ui.confirmDialog = async () => true;
  assert.equal(await ui.confirmLeave('#/addons'), true);
  assert.equal(location.hash, '#/addons');
  assert.equal(vm.runInContext('Object.keys(state.dirtyChanges).length', ui), 0);
  assert.equal(await ui.confirmLeave('#/health'), true);
});

test('route renders failures from async views instead of swallowing them', async () => {
  let markup = '';
  const location = {hash:'#/health', pathname:'/', search:''};
  const {ui} = withApp({location, document:{querySelector:selector => selector === '#content' ? {set innerHTML(v){ markup = v; }} : null, querySelectorAll:() => []}});
  ui.api = async () => { throw new Error('Health <check> failed'); };
  await ui.route();
  assert.match(markup, /Couldn’t load this page/);
  assert.match(markup, /Health &lt;check&gt; failed/);
});

test('restore results expose undo backups for stack and single add-on restores', () => {
  const {ui} = withApp();
  assert.deepEqual(JSON.parse(JSON.stringify(ui.undoTargets({undo_backups:{'plugin.video.pov':'u1','skin.x':'u2'}}))), [{addonId:'plugin.video.pov',backupId:'u1'},{addonId:'skin.x',backupId:'u2'}]);
  assert.deepEqual(JSON.parse(JSON.stringify(ui.undoTargets({undo_backup_id:'u3'}, 'plugin.video.fen'))), [{addonId:'plugin.video.fen',backupId:'u3'}]);
  assert.equal(ui.undoTargets({restored:true}).length, 0);
  const summary = ui.restoreSummary({restored:['a','b'], skipped:['c'], restart_required:true}, ui.undoTargets({undo_backups:{a:'u1',b:'u2'}}));
  assert.match(summary, /2 add-ons restored · 1 skipped\. Undo backups: u1, u2\./);
});

test('cached rows show age, status and escaped sources', () => {
  const {ui} = withApp();
  assert.equal(ui.formatAge(5), 'just now');
  assert.equal(ui.formatAge(600), '10 min ago');
  assert.equal(ui.formatAge(7200), '2 h ago');
  assert.equal(ui.formatAge(200000), '2 d ago');
  assert.equal(ui.formatAge(undefined), '—');
  const row = ui.cachedRowMarkup({id:'r1', label:'<b>Kids</b>', source:'plugin://plugin.video.x/?a="1"'}, {items:12, age_seconds:90, stale:false}, 0);
  assert.match(row, /&lt;b&gt;Kids&lt;\/b&gt;/);
  assert.match(row, /a=&quot;1&quot;/);
  assert.match(row, /Fresh/);
  assert.match(row, />12</);
  assert.match(ui.cachedRowMarkup({id:'r2', label:'x', source:'plugin://x/'}, undefined, 1), /Not cached yet/);
});

test('search results cannot inject markup through add-on ids', async () => {
  let markup = '';
  const {ui} = withApp({document:{querySelector:selector => selector === '#content' ? {set innerHTML(v){ markup = v; }} : {value:''}, querySelectorAll:() => []}});
  ui.api = async () => ({count:1, results:[{addon_id:"x');alert(1);//<img src=x>", addon_name:'<img src=x onerror=alert(1)>', id:'a', value:'v', editable:true}]});
  await ui.searchView('x');
  assert.doesNotMatch(markup, /<img/);
  assert.doesNotMatch(markup, /onclick/);
  assert.ok(markup.includes('href="#/addon/x&#39;)%3Balert(1)%3B%2F%2F%3Cimg%20src%3Dx%3E"'));
});

test('navigation offers Home layout only for a supported skin and hides absent add-ons', () => {
  const {ui} = withApp();
  const routes = groups => groups.flatMap(group => group.items.map(item => item[1]));
  const generic = routes(ui.navGroups({stack:{skin:{addon_id:'skin.estuary', bingie_like:false}, pov:{addon_id:'plugin.video.pov'}}}));
  assert.equal(generic.includes('#/widgets'), false);
  assert.equal(generic.includes('#/pov'), true);
  assert.equal(generic.includes('#/fen'), false);
  assert.equal(generic.includes('#/cached-rows'), true);
  const supported = routes(ui.navGroups({stack:{skin:{addon_id:'skin.bingie', bingie_like:true}}}));
  assert.equal(supported.includes('#/widgets'), true);
});

test('web sources contain no inline event handler attributes', () => {
  const files = fs.readdirSync(path.resolve(__dirname, '../web')).filter(name => /\.(js|html)$/.test(name));
  assert.ok(files.includes('index.html') && files.includes('app.js'));
  for (const name of files) {
    const text = web(name);
    assert.doesNotMatch(text, /\son[a-z]+\s*=\s*["'\\]/i, `${name} contains an inline on*= handler`);
    assert.doesNotMatch(text, /javascript:/i, `${name} contains a javascript: URL`);
  }
});

test('index.html loads only local scripts under a strict script-src policy', () => {
  const html = web('index.html');
  assert.match(html, /Content-Security-Policy" content="[^"]*script-src 'self'/);
  assert.doesNotMatch(html, /<script(?![^>]*\ssrc=)[^>]*>/);
  assert.match(html, /<label for="globalSearch"/);
  const scripts = [...html.matchAll(/<script src="([^"]+)"/g)].map(match => match[1]);
  assert.equal(scripts[0], 'core.js');
});

function fakeDom() {
  const make = tag => ({tagName:tag.toUpperCase(), children:[], listeners:{}, textContent:'', className:'', parent:null, removed:false, disabled:false,
    append(...nodes){ for (const node of nodes) if (node && typeof node === 'object') { node.parent = this; this.children.push(node); } },
    setAttribute(){}, addEventListener(type, fn){ (this.listeners[type] ||= []).push(fn); },
    remove(){ this.removed = true; if (this.parent) this.parent.children = this.parent.children.filter(child => child !== this); }});
  const body = make('body');
  return {body, createElement:make, getElementById:id => body.children.find(child => child.id === id) || null, querySelector:() => null, querySelectorAll:() => []};
}
function toastHarness() {
  const timers = [], hashListeners = [], dom = fakeDom();
  let clock = 1000;
  const FakeDate = class extends Date { static now() { return clock; } };
  const harness = withApp({document:dom, Date:FakeDate, setTimeout:(fn, ms) => { timers.push({fn, ms}); return timers.length; },
    window:{addEventListener:(type, fn) => { if (type === 'hashchange') hashListeners.push(fn); }}, location:{hash:'#/addon/plugin.video.pov', pathname:'/', search:''}});
  const toasts = () => dom.getElementById('toasts')?.children || [];
  return {...harness, dom, timers, hashListeners, toasts, advance:ms => { clock += ms; }};
}
const click = async button => { for (const fn of button.listeners.click) await fn({currentTarget:button}); };

test('action toasts expire after a minute and on navigation', () => {
  const h = toastHarness();
  h.ui.toast('Saved', 'ok', {actions:[{label:'Undo', run:() => {}}]});
  assert.equal(h.toasts().length, 1);
  assert.equal(h.timers.at(-1).ms, 60000);
  h.hashListeners.forEach(fn => fn());
  assert.equal(h.toasts().length, 0);
  h.ui.toast('Saved', 'ok', {actions:[{label:'Undo', run:() => {}}]});
  h.timers.at(-1).fn();
  assert.equal(h.toasts().length, 0);
  h.ui.toast('Failed', 'error');
  assert.equal(h.timers.length, 2, 'plain error toasts still stay until dismissed');
});

test('an expired action toast does nothing even when its timer fired late', async () => {
  const h = toastHarness();
  let ran = 0;
  h.ui.toast('Saved', 'ok', {actions:[{label:'Undo', run:() => { ran++; }}]});
  h.advance(61000);
  await click(h.toasts()[0].children[1]);
  assert.equal(ran, 0);
  assert.equal(h.toasts().length, 0);
});

test('settings save offers a clearly labelled restore that asks first after the quick-undo window', async () => {
  const h = toastHarness();
  const posts = [], confirms = [];
  h.ui.api = async (pathName, body) => { posts.push({pathName, body}); return {restored:true}; };
  h.ui.apiMethod = async () => ({changed_count:2, backup_id:'b1'});
  h.ui.route = async () => {};
  h.ui.confirmDialog = async options => { confirms.push(options.title); return confirms.length > 1 ? false : true; };
  vm.runInContext('state.writeEnabled = true; state.dirtyAddon = "plugin.video.pov"; state.dirtyChanges = {a:{value:"1"}, b:{value:"2"}};', h.ui);
  await h.ui.saveDirty();
  const button = h.toasts()[0].children[1];
  assert.equal(button.textContent, 'Restore settings from before this save');
  h.advance(30000);
  await click(button);
  assert.deepEqual(confirms, ['Save 2 changes?', 'Restore this backup?']);
  assert.equal(posts.length, 0, 'declining the late confirmation restores nothing');
});

function viewHarness(replies) {
  const elements = new Map(), posts = [], confirms = [];
  const element = selector => { if (!elements.has(selector)) elements.set(selector, {textContent:'', innerHTML:'', dataset:{}}); return elements.get(selector); };
  const healthButton = {textContent:'Re-apply', dataset:{healthAction:'/api/baseline/apply', healthLabel:'Protected settings', healthDetail:'1 changed: Max resolution is 720p, expected 1080p'}};
  const {ui} = withApp({document:{querySelector:element, querySelectorAll:selector => selector === '[data-health-action]' ? [healthButton] : []}});
  ui.api = async (pathName, body) => { if (body) { posts.push(pathName); return {applied:[], failed:[], detail:'done'}; } return replies[pathName]; };
  ui.confirmDialog = async options => { confirms.push(options); return false; };
  return {ui, element, posts, confirms, healthButton};
}

test('Restore tested fixes asks before overwriting add-on files', async () => {
  const h = viewHarness({'/api/status':{write_enabled:true}, '/api/fixes':{bundled:true, repairable:true, healthy:false, detail:'x', groups:[{label:'POV playback', status:'changed'}]}});
  await h.ui.fixesView();
  await h.element('#restoreFixes').onclick({currentTarget:{}});
  assert.equal(h.confirms.length, 1);
  assert.equal(h.confirms[0].title, 'Restore tested fixes?');
  assert.match(h.confirms[0].detail, /POV playback/);
  assert.deepEqual(h.posts, [], 'declined: nothing is repaired');
});

test('Health Re-apply asks before overwriting protected settings', async () => {
  const h = viewHarness({'/api/health':{status:'warning', checks:[{label:'Protected <settings>', detail:'d', status:'warning', action:{label:'Re-apply', path:'/api/baseline/apply'}}]}});
  await h.ui.healthView();
  assert.match(h.element('#content').innerHTML, /data-health-label="Protected &lt;settings&gt;"/);
  await h.healthButton.onclick({currentTarget:{}});
  assert.equal(h.confirms.length, 1);
  assert.match(h.confirms[0].title, /Re-apply: Protected settings\?/);
  assert.match(h.confirms[0].detail, /expected 1080p/);
  assert.deepEqual(h.posts, []);
});

test('cached-row Pages field matches the server limit of five', () => {
  assert.match(web('app.js'), /id="cachePages" type="number" min="1" max="5"/);
  assert.match(fs.readFileSync(path.resolve(__dirname, '../src/kodi_manager/widget_cache.py'), 'utf8'), /^MAX_PAGES = 5$/m);
});

test('a refused settings batch highlights the setting named in details.setting_id', async () => {
  const field = id => { const classes = new Set(), attrs = {}; return {dataset:{setting:id}, type:'text', classes, attrs, focused:false,
    classList:{add:c => classes.add(c), remove:c => classes.delete(c)}, setAttribute:(k, v) => { attrs[k] = v; }, removeAttribute:k => { delete attrs[k]; }, focus(){ this.focused = true; }}; };
  const fields = [field('timeout'), field('quality')];
  const {ui} = withApp({document:{querySelector:() => null, querySelectorAll:selector => selector === '[data-setting]' ? fields : selector === '.setting-invalid' ? fields.filter(f => f.classes.has('setting-invalid')) : []}});
  ui.confirmDialog = async () => true;
  ui.apiMethod = async () => { throw Object.assign(new Error('quality: Value not in options'), {status:400, code:'bad_request', details:{setting_id:'quality'}}); };
  vm.runInContext('state.writeEnabled = true; state.dirtyAddon = "plugin.video.pov"; state.dirtyChanges = {timeout:{value:"5"}, quality:{value:"8K"}};', ui);
  await assert.rejects(ui.saveDirty(), /quality: Value not in options/);
  assert.equal(fields[1].classes.has('setting-invalid'), true);
  assert.equal(fields[1].attrs['aria-invalid'], 'true');
  assert.equal(fields[1].focused, true);
  assert.equal(fields[0].classes.has('setting-invalid'), false);
  assert.equal(vm.runInContext('Object.keys(state.dirtyChanges).length', ui), 2, 'unsaved edits are kept');
});
