const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function page(extra = {}) {
  const ui = {URL, URLSearchParams, console, setTimeout, clearTimeout, setInterval, clearInterval,
    localStorage:{getItem:()=>null}, ...extra};
  vm.createContext(ui);
  for (const name of ['core.js', 'widgets.js', 'charts.js', 'status.js', 'settings-ui.js', 'app.js']) {
    const script = fs.readFileSync(path.resolve(__dirname, '../web', name), 'utf8');
    vm.runInContext(name === 'app.js' ? script.replace(/boot\(\)\.catch[^\n]+;\s*$/, '') : script, ui);
  }
  return ui;
}

test('search finds purposes and dependents, and review excludes disabled dependencies', () => {
  const ui = page();
  const addons = [
    {addon_id:'skin.test', name:'Skin', role:'skin', enabled:true, cleanup:{code:'keep'}},
    {addon_id:'script.shared', name:'Shared', purpose:'Provides menus', role:'library', enabled:false,
      required_by:[{addon_id:'skin.test', name:'Skin'}], cleanup:{code:'dependency'}},
    {addon_id:'plugin.old', name:'Old', role:'video', enabled:false, cleanup:{code:'review_disabled'}}
  ];
  assert.equal(ui.filteredAddons(addons, 'menus').length, 1);
  assert.equal(ui.filteredAddons(addons, 'skin.test', 'library')[0].addon_id, 'script.shared');
  assert.equal(ui.filteredAddons(addons, '', 'all', 'review_disabled')[0].addon_id, 'plugin.old');
  assert.equal(ui.filteredAddons(addons, '', 'all', 'disabled').length, 2);
  assert.equal(ui.filteredAddons(addons, '', 'system').length, 0);
});

test('unknown service state stays unknown and metadata is escaped in rows and explanations', () => {
  const ui = page();
  const addon = {addon_id:'plugin.test', name:'<script>bad</script>', installed:true, enabled:null,
    purpose:'<img src=x>', role_label:'Video add-on', has_service:null,
    cleanup:{label:'Check usage', detail:'<iframe>bad</iframe>'},
    required_by:[{addon_id:'skin.test', name:'<b>Skin</b>', enabled:false, optional:true}]};
  const row = ui.addonRowMarkup(addon);
  assert.match(row, /Enabled state unknown/);
  assert.doesNotMatch(row, /Background service when enabled|<script>|<img |<iframe>/);
  assert.match(row, /&lt;img/);
  assert.match(row, /\(disabled\).*\(optional\)/);
  assert.match(ui.addonExplanationMarkup(addon), /&lt;iframe/);
  addon.has_service = true;
  assert.match(ui.addonRowMarkup(addon), /Background service when enabled/);
  assert.equal(ui.addonExplanationMarkup({}), '');
});

test('all add-ons controls update filtered rows, match count and empty state', async () => {
  const controls = {};
  const document = {querySelector:selector => controls[selector]};
  const ui = page({document});
  ui.api = async () => [{addon_id:'plugin.old', name:'Old', installed:true, enabled:false,
    role:'video', cleanup:{code:'review_disabled'}}, {addon_id:'xbmc.python', installed:true,
    role:'system', cleanup:{code:'keep'}}];
  ui.out = html => {
    assert.match(html, /including 1 Kodi components/);
    assert.match(html, /current profile/);
    for (const id of ['filter','addonRole','addonReview','addonMatches','addonList']) controls['#'+id] = {value:id === 'filter' ? '' : 'all'};
  };
  await ui.allAddons();
  assert.equal(controls['#addonMatches'].textContent, '2 of 2 entries');
  controls['#addonReview'].value = 'review_disabled';
  controls['#addonReview'].onchange();
  assert.equal(controls['#addonMatches'].textContent, '1 of 2 entries');
  assert.doesNotMatch(controls['#addonList'].innerHTML, /xbmc.python/);
  controls['#filter'].value = 'no match';
  controls['#filter'].oninput();
  assert.match(controls['#addonList'].innerHTML, /No add-ons match/);
});
