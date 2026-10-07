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
  const ui = {console:{error(){}}, setTimeout, clearTimeout, setInterval, clearInterval, URLSearchParams,
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
  ui.fetch = async () => response(409, {ok:false, error:{code:'kodi_busy', message:'Kodi is playing'}});
  await assert.rejects(ui.api('/api/stack/restore', {backup_id:'x'}), error => error.status === 409 && error.code === 'kodi_busy');
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
