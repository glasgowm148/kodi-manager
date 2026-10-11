const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

/* The scripts load into one page in this order (index.html). */
const web = name => fs.readFileSync(path.resolve(__dirname, '../web', name), 'utf8');
function page(extra = {}) {
  const storage = new Map();
  const ui = {URL, URLSearchParams, console:{error(){}}, setTimeout, clearTimeout, setInterval, clearInterval,
    localStorage:{getItem:key => storage.get(key) ?? null, setItem:(key, value) => storage.set(key, String(value)), removeItem:key => storage.delete(key)}, ...extra};
  vm.createContext(ui);
  for (const name of ['core.js', 'widgets.js', 'charts.js', 'status.js']) vm.runInContext(web(name), ui);
  vm.runInContext(web('app.js').replace(/boot\(\)\.catch[^\n]+;\s*$/, ''), ui);
  return {ui, storage};
}
const {ui} = page();
const plain = value => JSON.parse(JSON.stringify(value));
const NOW = 1_800_000_000;

test('nice ticks are round, cover the data and survive flat or missing data', () => {
  assert.deepEqual(plain(ui.niceTicks(0, 2900, 4)), {min:0, max:3000, ticks:[0, 1000, 2000, 3000]});
  assert.deepEqual(plain(ui.niceTicks(0, 2, 4).ticks), [0, 0.5, 1, 1.5, 2]);
  const flat = ui.niceTicks(5, 5);
  assert.ok(flat.min <= 5 && flat.max >= 5 && flat.max > flat.min);
  assert.deepEqual(plain(ui.niceTicks(NaN, 3)), {min:0, max:1, ticks:[0, 1]});
  const scale = ui.scaleLinear([0, 10], [100, 200]);
  assert.equal(scale(5), 150);
  assert.equal(scale.invert(150), 5);
});

test('lines break at missing samples and at long gaps; buckets take the median', () => {
  const t = [0, 900, 1800, 2700, 9000, 9900];
  const segments = ui.splitSegments(t, [1, 2, null, 4, 5, 6], 2700);
  assert.deepEqual(plain(segments), [[[0, 1], [900, 2]], [[2700, 4]], [[9000, 5], [9900, 6]]]);
  assert.deepEqual(plain(ui.splitSegments([], [])), []);
  const buckets = ui.bucketMedian([0, 10, 20, 7200], [[1, 3, 100, null]], 7200);
  assert.deepEqual(plain(buckets), {t:[3600, 10800], values:[[3, null]]});
  assert.equal(ui.median([null, 4, 1, 9]), 4);
  assert.equal(ui.median([]), null);
});

test('number and time formats read naturally', () => {
  assert.equal(ui.formatMB(820), '820 MB');
  assert.equal(ui.formatMB(1229), '1.2 GB');
  assert.equal(ui.formatMB(undefined), '—');
  assert.equal(ui.formatMs(412), '412 ms');
  assert.equal(ui.formatMs(1500), '1.5 s');
  assert.equal(ui.formatBytes(2048), '2.0 KB');
  assert.equal(ui.formatBytes(1_900_000), '1.8 MB');
  assert.equal(ui.formatRelative(30), 'just now');
  assert.equal(ui.formatRelative(3 * 3600), '3 hours ago');
  assert.equal(ui.formatRelative(-2 * 86400), 'in 2 days');
  assert.equal(ui.formatRelative(60 * 60), '60 minutes ago');
  assert.equal(typeof ui.parseStamp('20261011-031205-abc'), 'number');
  assert.equal(ui.parseStamp('nightly'), null);
});

test('sparklines are labelled images, escape their label and are empty without data', () => {
  const svg = ui.sparkline([1, 2, 3], [5, null, 7], {label:'Free <memory>'});
  assert.match(svg, /role="img"/);
  assert.match(svg, /aria-label="Free &lt;memory&gt;"/);
  assert.doesNotMatch(svg, /NaN|undefined/);
  assert.equal(ui.sparkline([1, 2], [null, null]), '');
  assert.equal(ui.sparkline([], []), '');
  assert.match(ui.sparkline([1, 2, 3], [0, 2, 1], {kind:'bars'}), /class="spark-bar"/);
});

test('charts escape series names, size margins to their labels and never draw NaN', () => {
  const spec = {title:'Answer <time>', summary:'S', t:[0, 900, 1800], format:ui.formatMs,
    series:[{name:'<img src=x>', values:[100, null, 2500]}, {name:'Trakt', values:[200, 300, 250]}]};
  const svg = ui.chartSvg(spec, 640);
  assert.doesNotMatch(svg, /<img/);
  assert.match(svg, /&lt;img src=x&gt;/);
  assert.doesNotMatch(svg, /NaN|undefined/);
  assert.match(svg, /class="line s2"/);
  const layout = ui.chartLayout(spec, 640);
  assert.ok(layout.left >= '2.5 s'.length * 7, 'tick labels fit on the left');
  assert.equal(layout.labels, true);
  assert.equal(ui.chartLayout(spec, 300).labels, false, 'no end labels when they would crowd a narrow chart');
  const single = ui.chartSvg({title:'One', t:[5], series:[{name:'A', values:[3]}]}, 400);
  assert.doesNotMatch(single, /NaN|Infinity/);
  const cols = ui.chartSvg({title:'C', kind:'columns', slot:86400, t:[0, 86400], series:[{name:'N', values:[1, 0]}, {name:'M', values:[1, 2]}]}, 500);
  assert.match(cols, /class="col s1"/);
  assert.doesNotMatch(cols, /NaN/);
  assert.equal(ui.nearestIndex([0, 10, 20], 14), 1);
  assert.equal(ui.nearestIndex([], 4), -1);
});

test('chart figures show an empty state, a legend only for several series and an escaped table', () => {
  ui.resetCharts();
  const empty = ui.chartFigure({title:'Memory', t:[], series:[{name:'Free', values:[]}], empty:'No history <yet>'});
  assert.match(empty, /chart-empty">No history &lt;yet&gt;/);
  assert.doesNotMatch(empty, /data-chart-plot/);
  const one = ui.chartFigure({title:'Rows', t:[NOW], series:[{name:'Failing', values:[2]}]});
  assert.doesNotMatch(one, /chart-legend/);
  assert.match(one, /Show as table/);
  const two = ui.chartFigure({title:'Latency', t:[NOW], format:ui.formatMs, series:[{name:'<b>TorBox</b>', values:[null], missing:'timed out'}, {name:'TMDb', values:[140]}]});
  assert.match(two, /chart-legend/);
  assert.match(two, /&lt;b&gt;TorBox&lt;\/b&gt;/);
  assert.match(two, /<td>timed out<\/td><td>140 ms<\/td>/);
});

test('API error codes become plain English with a next step', () => {
  const f = code => ui.friendlyError(Object.assign(new Error('raw'), {code}));
  assert.equal(f('playback_active').title, 'Something is playing on the TV.');
  assert.match(f('playback_active').hint, /viewing has finished/);
  assert.match(f('write_disabled').hint, /Enable writes/);
  assert.match(f('network').title, /reach the TV/);
  assert.equal(f('bad_request').hint, 'raw');
  assert.equal(ui.friendlyError(new Error('Restore failed')).title, 'Restore failed');
  assert.equal(ui.friendlyMessage(Object.assign(new Error('x'), {code:'host_not_allowed'})).startsWith('Open the dashboard by the TV’s IP address.'), true);
});

const history = {resolution_seconds:900, hosts:['TorBox', 'Trakt'], latency_ms:{TorBox:[300, null, 280], Trakt:[200, null, null]},
  series:{t:[NOW - 1800, NOW - 900, NOW], memory_available_mb:[1200, 1100, 1000], rows_failing:[0, 1, 2], network_status:['ok', null, 'warning']}};

test('overview tiles say one plain thing each, with the right tone', () => {
  assert.equal(ui.memoryTile({status:'unknown', detail:'n/a'}, null).tone, 'muted');
  const memory = ui.memoryTile({status:'ok', available_mb:1180, total_mb:2900, kodi_mb:612}, history);
  assert.equal(memory.value, '1.2 GB free');
  assert.match(memory.spark, /<svg/);
  assert.equal(ui.internetTile(null, null).value, 'Not checked yet');
  const net = ui.internetTile({status:'error', age_seconds:120, hosts:[{name:'TorBox', seconds:null}, {name:'TMDb', seconds:0.2}]}, history);
  assert.equal(net.tone, 'bad');
  assert.equal(net.value, '1 of 2 not answering');
  assert.equal(ui.probeSeries(history).t.length, 2, 'only samples with a new check');
  assert.equal(ui.rowsTile({cached:0}, null).tone, 'muted');
  assert.equal(ui.rowsTile({cached:14, failing:2, persistent:0}, history).value, '2 of 14 failing');
  assert.equal(ui.rowsTile({cached:14, failing:2, persistent:1}, history).tone, 'bad');
  assert.equal(ui.backupsTile({count:0}, NOW).value, 'No checkpoints yet');
  const stamp = t => { const d = new Date(t * 1000), p = n => String(n).padStart(2, '0'); return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`; };
  assert.equal(ui.backupsTile({count:3, last:{timestamp:stamp(NOW - 5 * 3600)}, times:[stamp(NOW - 5 * 3600)]}, NOW).tone, 'ok');
  assert.equal(ui.backupsTile({count:3, last:{timestamp:stamp(NOW - 5 * 86400)}}, NOW).tone, 'warn');
  assert.equal(ui.protectionTile({fixes:{healthy:false, attention:1}, baseline:{total:3, drifted:0}}).tone, 'warn');
  assert.equal(ui.protectionTile({fixes:{healthy:null}, baseline:null}).tone, 'muted');
  const accounts = ui.accountsTile([{id:'trakt', label:'Trakt sign-in (POV)', status:'ok', days_left:60, renews:true}, {id:'torbox', label:'TorBox subscription', status:'warning', days_left:9, detail:'Renew soon.'}]);
  assert.equal(accounts.value, 'TorBox ends in 9 days');
  assert.equal(accounts.tone, 'warn');
  assert.equal(ui.accountsTile([]).value, 'Not checked yet');
});

test('the TV verdict counts what needs a look and respects playback', () => {
  const o = {playback:{active:true, title:'<b>Bluey</b>'}, profile:'Kids <x>', kodi_version:'22.0', write_enabled:false};
  const tiles = [{name:'Memory', tone:'ok'}, {name:'Home rows', tone:'warn', href:'#/rows', value:'2 of 14 failing'}, {name:'Accounts', tone:'bad', href:'#/accounts', value:'x'}];
  const verdict = ui.overviewVerdict(o, tiles);
  assert.equal(verdict.headline, '2 things need a look');
  assert.equal(verdict.tone, 'bad');
  assert.match(verdict.detail, /waits until viewing has finished/);
  const markup = ui.screenMarkup(o, verdict, '12:00');
  assert.doesNotMatch(markup, /<b>Bluey|<x>/);
  assert.match(markup, /Profile: Kids &lt;x&gt;/);
  assert.match(markup, /View only/);
  assert.match(markup, /href="#\/rows"/);
  assert.equal(ui.overviewVerdict({playback:{active:false}}, [{name:'Memory', tone:'ok'}]).headline, 'All good');
  assert.match(ui.overviewVerdict({playback:{active:false}}, []).detail, /good time to make changes/);
  assert.match(ui.tileMarkup({key:'k', name:'<i>', icon:'memory', tone:'ok', value:'<v>', text:'<t>', href:'#/trends'}), /&lt;i&gt;.*&lt;v&gt;.*&lt;t&gt;/s);
});

test('row health groups, sorts, filters and escapes rows', () => {
  const cache = {entries:[
    {source:'plugin://plugin.video.pov/?name=Fresh', items:10, age_seconds:60, stale:false, health:{}},
    {source:'plugin://plugin.video.pov/?name=Broken', items:4, age_seconds:9000, stale:false, health:{failures:4, reason:'unavailable'}},
    {source:'plugin://plugin.video.pov/?name=Old', items:7, age_seconds:99999, stale:true, health:{}}]};
  const cards = ui.rowCards(cache, [{source:'plugin://plugin.video.pov/?name=Fresh', label:'Saved <name>'}, {source:'plugin://x/?y', label:'Waiting'}]);
  assert.deepEqual(plain(cards.map(c => c.state)), ['fresh', 'persistent', 'stale', 'waiting']);
  assert.equal(cards[0].label, 'Saved <name>');
  assert.deepEqual(plain(ui.sortRowCards(cards).map(c => c.state)), ['persistent', 'stale', 'waiting', 'fresh']);
  assert.deepEqual(plain(ui.filterRowCards(cards, 'attention').map(c => c.state)), ['persistent', 'stale']);
  assert.deepEqual(plain(ui.filterRowCards(cards, 'all', 'waiting').map(c => c.label)), ['Waiting']);
  const markup = ui.rowCardMarkup(cards[0], NOW);
  assert.match(markup, /Saved &lt;name&gt;/);
  assert.doesNotMatch(markup, /<name>/);
  assert.match(ui.rowCardMarkup(cards[1], NOW), /Keeps failing/);
  const strip = ui.posterStrip([{title:'<b>A</b>', poster:'https://image.tmdb.org/t/p/w185/a.jpg'}, {title:'B', poster:'https://evil.example/b.jpg'}, {title:'C', poster:'javascript:alert(1)'}]);
  assert.match(strip, /src="https:\/\/image\.tmdb\.org\/t\/p\/w185\/a\.jpg"/);
  assert.match(strip, /referrerpolicy="no-referrer"/);
  assert.doesNotMatch(strip, /evil\.example|javascript:/);
  assert.match(strip, /alt="&lt;b&gt;A&lt;\/b&gt;"/);
});

test('checkpoints are counted per day and by kind', () => {
  const day = t => { const d = new Date(t * 1000), p = n => String(n).padStart(2, '0'); return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}00`; };
  const per = ui.checkpointsPerDay([day(NOW), day(NOW - 3600), day(NOW - 3 * 86400), 'junk'], NOW, 7);
  assert.equal(per.t.length, 7);
  assert.equal(per.counts.reduce((a, b) => a + b, 0) >= 3, true);
  assert.equal(per.counts[6] >= 1, true);
  const spec = ui.backupChartSpec([{timestamp:day(NOW), note:'nightly', kind:'stack'}, {timestamp:day(NOW), kind:'pipeline'}, {timestamp:day(NOW - 86400), kind:'stack'}], NOW, 30);
  const totals = spec.series.map(s => s.values.reduce((a, b) => a + b, 0));
  assert.deepEqual(plain(totals), [1, 1, 1]);
  assert.deepEqual(plain(spec.series.map(s => s.name)), ['Nightly', 'Manual', 'Playback settings']);
});

test('navigation keeps every old route, groups pages by task and maps add-on pages to their group', () => {
  const groups = ui.navGroups({stack:{skin:{addon_id:'skin.bingie', bingie_like:true}, pov:{addon_id:'plugin.video.pov'}}});
  const routes = groups.flatMap(g => g.items.map(item => item[1]));
  for (const route of ['#/dashboard', '#/health', '#/fixes', '#/pipeline', '#/playback-test', '#/widgets', '#/accounts', '#/addons', '#/install', '#/backups', '#/cached-rows', '#/kodi-logs', '#/logs', '#/setup', '#/diagnostics', '#/pov', '#/trends', '#/rows', '#/components'])
    assert.ok(routes.includes(route), route);
  assert.deepEqual(plain(groups.map(g => g.group)), ['Status', 'Home screen', 'Add-ons & settings', 'Backups & recovery', 'Accounts', 'Advanced']);
  assert.equal(ui.routeGroup('#/addon/plugin.video.pov', groups).key, 'addons');
  assert.equal(ui.routeGroup('#/kodi-logs', groups).key, 'advanced');
  assert.equal(ui.routeGroup('#/search', groups), null);
  assert.match(ui.viewOnlyBanner({write_enabled:false}), /View only/);
  assert.equal(ui.viewOnlyBanner({write_enabled:true}), '');
});

test('arrow keys move focus to the nearest control in that direction', () => {
  const box = (left, top, w = 100, h = 40) => ({left, top, right:left + w, bottom:top + h});
  const from = box(0, 0);
  const candidates = [{id:'right', rect:box(120, 0)}, {id:'far-right', rect:box(400, 0)}, {id:'below', rect:box(0, 60)}, {id:'diag', rect:box(120, 300)}];
  assert.equal(ui.spatialPick(from, candidates, 'right').id, 'right');
  assert.equal(ui.spatialPick(from, candidates, 'down').id, 'below');
  assert.equal(ui.spatialPick(from, candidates, 'up'), null);
  assert.equal(ui.spatialPick(from, candidates, 'left'), null);
});

test('theme choice cycles and ignores stored junk', () => {
  const {ui:fresh, storage} = page();
  assert.equal(fresh.storedTheme(), 'auto');
  assert.equal(fresh.nextTheme('auto'), 'light');
  assert.equal(fresh.nextTheme('light'), 'dark');
  assert.equal(fresh.nextTheme('dark'), 'auto');
  storage.set('km_theme', '<script>');
  assert.equal(fresh.storedTheme(), 'auto');
  fresh.saveTheme('dark');
  assert.equal(storage.get('km_theme'), 'dark');
  fresh.saveTheme('auto');
  assert.equal(storage.has('km_theme'), false);
});

test('index.html loads the chart and status scripts before app.js', () => {
  const scripts = [...web('index.html').matchAll(/<script src="([^"]+)"/g)].map(m => m[1]);
  assert.deepEqual(scripts, ['core.js', 'settings-ui.js', 'widgets.js', 'charts.js', 'status.js', 'app.js']);
});
