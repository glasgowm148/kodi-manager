const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const core = fs.readFileSync(path.resolve(__dirname, '../web/core.js'), 'utf8');
const app = fs.readFileSync(path.resolve(__dirname, '../web/app.js'), 'utf8')
  .replace(/boot\(\)\.catch[^\n]+;\s*$/, '');
const ui = {localStorage: {getItem: () => ''}};
vm.createContext(ui);
vm.runInContext(core, ui);
vm.runInContext(app, ui);

test('statuses distinguish confirmed installation, enablement and leftover config', () => {
  const cases = [
    [{addon_id:'skin.bingie', active:true}, 'Active', 'ok'],
    [{installed:true, enabled:true}, 'Enabled', 'ok'],
    [{installed:true, enabled:false}, 'Disabled', 'warn'],
    [{installed:true, enabled:null}, 'Detected', 'info'],
    [{installed:null, config_present:true}, 'Config only', 'warn'],
    [{installed:false, config_present:true}, 'Config only', 'warn'],
    [{installed:false, config_present:false}, 'Not found', 'muted'],
    [{installed:null, enabled:null}, 'Unknown', 'muted'],
    [{active:true}, 'Unknown', 'muted'],
    [{installed:'true', enabled:'true'}, 'Unknown', 'muted']
  ];
  for (const [addon, label, tone] of cases) {
    assert.equal(ui.dashboardStatus(addon).label, label);
    assert.equal(ui.dashboardStatus(addon).tone, tone);
  }
});

test('unknown boolean states never display positive or negative confirmation', () => {
  for (const value of [undefined, null, 'true', 'false', 0, 1]) {
    const markup = ui.dashboardFlag(value, 'Installed', 'Not found');
    assert.match(markup, />Unknown</);
    assert.doesNotMatch(markup, />Installed<|>Not found</);
  }
  assert.match(ui.dashboardFlag(true, 'Installed', 'Not found'), />Installed</);
  assert.match(ui.dashboardFlag(false, 'Installed', 'Not found'), />Not found</);
});

test('POV is detected from add-on index even with older service stack metadata', () => {
  const rows = ui.dashboardComponents({stack:{}}, [
    {addon_id:'plugin.video.pov', installed:true, enabled:false, config_present:true, version:'5.0'}
  ]);
  const pov = rows.find(row => row.key === 'pov');
  assert.equal(pov.status.label, 'Disabled');
  assert.match(ui.dashboardRow(pov), /href="#\/addon\/plugin.video.pov"/);
  assert.match(ui.dashboardRow(pov), /5\.0/);
  assert.equal(rows.find(row => row.key === 'fen').status.label, 'Not found');
});

test('most recent add-on enablement overrides earlier stack snapshot', () => {
  const pov = {addon_id:'plugin.video.pov', installed:true, enabled:true};
  const row = ui.dashboardComponents({stack:{pov}}, [{...pov, enabled:false}])
    .find(row => row.key === 'pov');
  assert.equal(row.status.label, 'Disabled');
});

test('active skin is confirmed only by a matching Kodi skin id', () => {
  let rows = ui.dashboardComponents({active_skin:{addon_id:'skin.bingie', name:'Bingie'}, stack:{}}, []);
  assert.equal(rows[0].status.label, 'Active');
  assert.equal(rows[0].addon.installed, true);
  rows = ui.dashboardComponents({active_skin:{}, stack:{skin:{active:true, enabled:null}}}, []);
  assert.equal(rows[0].status.label, 'Unknown');
});

test('config-only rows allow editing; missing rows have no settings action', () => {
  const rows = ui.dashboardComponents({stack:{}}, [
    {addon_id:'plugin.video.fen', installed:null, config_present:true, enabled:null}
  ]);
  assert.match(ui.dashboardRow(rows.find(r => r.key === 'fen')), /href="#\/addon\/plugin.video.fen"/);
  assert.doesNotMatch(ui.dashboardRow(rows.find(r => r.key === 'pov')), /href=/);
});

test('add-on metadata cannot inject HTML into dashboard', () => {
  const skin = ui.dashboardComponents({active_skin:{addon_id:'skin.bingie'}, stack:{}}, [
    {addon_id:'skin.bingie', name:'<img src=x onerror=alert(1)>', version:'<script>bad()</script>', installed:true}
  ])[0];
  const markup = ui.dashboardRow(skin);
  assert.doesNotMatch(markup, /<img|<script/);
  assert.match(markup, /&lt;img/);
});


test('protected-fix notice flags changed files and never claims unavailable checks passed', () => {
  assert.match(ui.dashboardFixNotice({healthy:true}), /Custom fixes intact/);
  assert.match(ui.dashboardFixNotice({healthy:false}), /Custom fixes need attention/);
  assert.equal(ui.dashboardFixNotice(null), '');
  assert.equal(ui.dashboardFixNotice({healthy:'true'}), '');
  assert.match(ui.dashboardFixNotice({healthy:false}), /href="#\/fixes"/);
});
