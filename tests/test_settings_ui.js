const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ui = {esc: value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]))};
vm.createContext(ui);
vm.runInContext(fs.readFileSync(path.resolve(__dirname, '../web/settings-ui.js'), 'utf8'), ui);

test('false is disabled, configured, and default rather than unset or changed', () => {
  for (const value of [false, 'false', '0', 'off']) {
    const state = ui.settingPresentationState({type:'bool', value, default:'false', default_known:true, editable:true});
    assert.equal(state.enabled, false);
    assert.equal(state.unset, false);
    assert.equal(state.isDefault, true);
    assert.equal(state.changed, false);
  }
});

test('unknown booleans remain unknown; text values never become enabled', () => {
  for (const value of [null, undefined, '', 'unexpected']) {
    const state = ui.settingPresentationState({type:'boolean', value, default:'true', editable:true});
    assert.equal(state.enabled, null);
    const control = ui.settingsControlMarkup({id:'enabled', type:'boolean', value, editable:true}, 0, true);
    assert.match(control, /selected disabled>Unknown/);
    assert.doesNotMatch(control, /value="true" selected/);
  }
  assert.equal(ui.settingPresentationState({type:'text', value:'true'}).enabled, null);
});

test('known false controls select Off without inventing a replacement value', () => {
  const control = ui.settingsControlMarkup({id:'enabled', type:'boolean', value:'0', editable:true}, 1, true);
  assert.match(control, /data-original="0"/);
  assert.match(control, /value="0" selected>Off/);
  assert.doesNotMatch(control, /selected>On/);
});

test('default comparison respects unknown defaults, numeric forms and empty defaults', () => {
  assert.equal(ui.settingPresentationState({type:'text', value:'x', default:'', default_known:false}).isDefault, null);
  assert.equal(ui.settingPresentationState({type:'text', value:'', default:'', default_known:true}).isDefault, true);
  assert.equal(ui.settingPresentationState({type:'number', value:'1.0', default:'1'}).changed, false);
  assert.equal(ui.settingPresentationState({type:'text', value:'x', default:'y'}).changed, true);
  assert.equal(ui.settingPresentationState({type:'text', value:'x', default:'', raw:{source:'raw'}}).isDefault, null);
});

test('unknown select values are preserved until user chooses a valid option', () => {
  const control = ui.settingsControlMarkup({id:'sort', type:'select', value:'old', editable:true, options:[{value:'new',label:'New'}]}, 2, true);
  assert.match(control, /value="old" selected disabled/);
  assert.match(control, /value="new">New/);
  assert.doesNotMatch(control, /value="new" selected/);
});

test('credentials are hidden in inputs and value summaries with explicit reveal', () => {
  const setting = {id:'trakt.token', type:'text', secret:true, value:'test-secret', default:'', default_known:true, editable:true};
  const markup = ui.settingsRowMarkup(setting, 3, true);
  assert.match(markup, /type="password"/);
  assert.match(markup, /data-secret="true"/);
  assert.match(markup, /data-reveal="setting-field-3"/);
  assert.match(markup, /data-current-label>Hidden/);
  assert.doesNotMatch(markup, />test-secret</);
  assert.equal(ui.settingPresentationState({id:'trakt.refresh_widgets',type:'boolean',value:'true'}).secret, false);
});

test('readonly and masked controls cannot silently become editable', () => {
  for (const setting of [{editable:false}, {editable:true,masked:true}]) {
    assert.match(ui.settingsControlMarkup({id:'x',type:'text',value:'hidden',...setting}, 4, true), / disabled/);
  }
  assert.match(ui.settingsControlMarkup({id:'x',type:'text',editable:true}, 4, false), / disabled/);
  assert.equal(ui.settingPresentationState({editable:true,masked:true}).readOnly, true);
});

test('read-only add-ons render disabled controls and explain why', async () => {
  let markup = '';
  ui.state = {dirtyChanges:{},writeEnabled:true};
  ui.api = async endpoint => endpoint === '/api/status' ? {write_enabled:true} : {name:'Fen Light', editable:false,
    read_only_reason:'Fen Light keeps these settings in its <own> database.',
    groups:[{label:'General',settings:[{id:'autoplay',type:'bool',value:'true',editable:true},{id:'timeout',type:'text',value:'20',editable:true}]}]};
  ui.clearDirty = () => {};
  ui.updateDirtyBar = () => {};
  ui.out = html => { markup = html; };
  ui.$ = () => ({value:'',addEventListener(){},classList:{toggle(){}}});
  ui.document = {querySelectorAll:() => []};
  await ui.renderAddonSettingsView('plugin.video.fenlight');
  assert.match(markup, /class="banner settings-readonly"/);
  assert.match(markup, /Fen Light keeps these settings in its &lt;own&gt; database\./);
  const controls = markup.match(/<(?:select|input) [^>]*data-setting=[^>]*>/g);
  assert.equal(controls.length, 2);
  for (const control of controls) assert.match(control, / disabled/);
});

test('edit state prefers the add-on read-only reason, then the write switch', () => {
  assert.deepEqual(JSON.parse(JSON.stringify(ui.settingsEditState({editable:false, read_only_reason:'Busy'}, true))), {canEdit:false,banner:'readonly',reason:'Busy'});
  assert.equal(ui.settingsEditState({editable:false, read_only_reason:null}, true).reason.length > 0, true);
  assert.equal(ui.settingsEditState({}, false).banner, 'writes');
  assert.equal(ui.settingsEditState({}, true).canEdit, true);
  assert.equal(ui.settingsEditState({editable:true}, true).canEdit, true);
});

test('addon view preserves native categories and starts with all settings', async () => {
  let markup = '';
  const calls = [];
  ui.state = {dirtyChanges:{},writeEnabled:false};
  ui.api = async endpoint => {
    calls.push(endpoint);
    return endpoint === '/api/status' ? {write_enabled:true} : {name:'POV', groups:[
      {label:'History & Lists',settings:[{id:'trakt.enabled',label:'Trakt history',type:'bool',value:'false',default:'false',editable:true}]},
      {label:'Artwork',settings:[{id:'default_addon_fanart',type:'text',value:'blue',default:'blue',editable:true}]}
    ]};
  };
  ui.clearDirty = () => { ui.state.dirtyChanges = {}; };
  ui.updateDirtyBar = () => {};
  ui.out = html => { markup = html; };
  ui.$ = selector => ({value:selector === '#settings-filter' ? 'all' : '',addEventListener(){},classList:{toggle(){}}});
  ui.document = {querySelectorAll:() => []};
  await ui.renderAddonSettingsView('plugin.video.pov');
  assert.equal(calls.join(','), '/api/status,/api/addons/plugin.video.pov/settings');
  assert.match(markup, /<h3>History &amp; Lists<\/h3>/);
  assert.match(markup, /<h3>Artwork<\/h3>/);
  assert.match(markup, /<select id="settings-filter"><option value="all">All settings/);
  assert.doesNotMatch(markup, /<h3>Accounts<\/h3>/);
  assert.match(markup, /Default: Off/);
});
