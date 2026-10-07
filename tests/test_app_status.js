const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const core = fs.readFileSync(path.resolve(__dirname, '../web/core.js'), 'utf8');
const source = fs.readFileSync(path.resolve(__dirname, '../web/app.js'), 'utf8')
  .replace(/boot\(\)\.catch[^\n]+;\s*$/, '');

function harness(readOnly = false) {
  const elements = new Map();
  const calls = [];
  const ui = {localStorage:{getItem:()=>''}, window:{}, alert:()=>{},
    document:{querySelector:selector=>{
      if (!elements.has(selector)) elements.set(selector, {});
      return elements.get(selector);
    }, querySelectorAll:()=>[]}, navigator:{clipboard:{writeText:async value=>{ui.copied=value;}}}};
  vm.createContext(ui);
  vm.runInContext(core, ui);
  vm.runInContext(source, ui);
  const pipe = {summary:{primary_player:{selection:'unknown'}, health:{warnings:[]}, accounts:{trakt:{status:'unknown',message:'Local settings cannot be read.'}}},
    nodes:[], edges:[], routing:{}, settings_groups:[], discovery:{id:'trakt.token',value:'sample-private-token'}};
  ui.api = async path => {
    calls.push(path);
    if (path === '/api/status') return {write_enabled:!readOnly};
    if (path === '/api/pipeline') return pipe;
    if (path === '/api/accounts') return {summary:{},groups:[]};
    throw new Error('Unexpected endpoint ' + path);
  };
  return {ui,elements,calls};
}

test('unknown integration retains read limitation and never implies absence or zero inspected fields', () => {
  const {ui} = harness();
  const markup = ui.integrationSummary({status:'unknown',refs_found:0,message:'Remote account settings cannot be read.'});
  assert.match(markup, /Account status unknown/);
  assert.match(markup, /Remote account settings cannot be read/);
  assert.doesNotMatch(markup, /No (?:configured|account) credentials|0 auth fields/);
  assert.match(ui.integrationSummary({status:'not found'}), /No account credentials found/);
  assert.match(ui.integrationSummary({status:'configured'}), /Credentials present/);
});

test('unknown boolean options preserve original value instead of silently selecting On', () => {
  const {ui} = harness();
  for (const value of [undefined,null,'','unexpected']) {
    for (const markup of [ui.controlFor({id:'flag',type:'bool',value,editable:true},''), ui.accountField({id:'flag',type:'bool',value,editable:true})]) {
      assert.match(markup, /disabled selected>Unknown/);
      assert.doesNotMatch(markup, /value="true" selected/);
      if (value === 'unexpected') assert.match(markup, /value="unexpected" disabled selected/);
    }
  }
  assert.match(ui.appBooleanOptions('0'), /value="0" selected>Off/);
});

test('read-only pipeline refresh/copy use supported reads and disable backup', async () => {
  const {ui,elements,calls} = harness(true);
  await ui.pipelineView();
  assert.deepEqual(calls, ['/api/status','/api/pipeline']);
  assert.equal(elements.get('#backupPipe').disabled, true);
  await elements.get('#backupPipe').onclick();
  assert.equal(calls.length, 2);
  await elements.get('#rescanPipe').onclick();
  assert.deepEqual(calls, ['/api/status','/api/pipeline','/api/status','/api/pipeline']);
  await elements.get('#copyPipe').onclick();
  assert.doesNotMatch(ui.copied, /sample-private-token/);
  assert.equal(calls.length, 4);
  assert.equal(vm.runInContext('state.writeEnabled',ui), false);
});

test('accounts cannot submit writes when writes are off', async () => {
  const {ui,elements,calls} = harness(true);
  await ui.accountsView();
  assert.equal(elements.get('#saveAccounts').disabled,true);
  await elements.get('#saveAccounts').onclick();
  assert.deepEqual(calls, ['/api/status','/api/accounts']);
});

test('cached rows page names skin-cached sources readably and escapes them', () => {
  const {ui} = harness();
  ui.URL = URL;
  assert.equal(ui.cacheSourceLabel('plugin://plugin.video.pov/?mode=build_movie_list&name=Family+movie+night'), 'Family movie night');
  assert.equal(ui.cacheSourceLabel('plugin://plugin.video.themoviedb.helper/?info=trakt_trending&tmdb_type=movie'), 'plugin.video.themoviedb.helper · trakt_trending');
  assert.equal(ui.cacheSourceLabel('not a url'), 'not a url');
  const row = ui.cachedEntryMarkup({source:'plugin://x/?name=%3Cimg%20src%3Dx%3E', items:3, age_seconds:7200, stale:false});
  assert.doesNotMatch(row, /<img/);
  assert.match(row, /2 h ago/);
});
