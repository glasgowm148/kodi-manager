const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ui = {URL, URLSearchParams, console, setTimeout, clearTimeout, setInterval, clearInterval,
  localStorage:{getItem:()=>null}};
vm.createContext(ui);
for (const name of ['core.js', 'widgets.js', 'charts.js', 'status.js', 'app.js']) {
  const script = fs.readFileSync(path.resolve(__dirname, '../web', name), 'utf8');
  vm.runInContext(name === 'app.js' ? script.replace(/boot\(\)\.catch[^\n]+;\s*$/, '') : script, ui);
}

test('retained lines are escaped and use recorded severity, even when payload says error', () => {
  const html = ui.logHistoryEntries([{timestamp:1800000000, level:'notice', line:'warning: <script>error</script>'}]);
  assert.doesNotMatch(html, /<script>|log-error/);
  assert.match(html, /&lt;script&gt;error&lt;\/script&gt;/);
  assert.match(html, /log-info/);
  assert.match(ui.logHistoryEntries([]), /No retained entries/);
});

test('history describes retention and unavailable collection instead of claiming clean logs', () => {
  const html = ui.logHistoryMarkup({counts:{errors:5, warnings:7, notices:2}, available:false, entries:[], total:14}, 'warning');
  assert.match(html, /past 24 hours/);
  assert.match(html, /Collection is unavailable/);
  assert.match(html, /5 errors · 7 warnings · 2 known notices/);
  assert.match(html, /data-history-level="warning" aria-pressed="true"/);
  assert.match(html, /Current raw log tail/);
});

test('catch-up and complete history are distinguished and older pages stay accessible', () => {
  const h = {available:true, catching_up:true, entries:[], has_more:true, total:200};
  assert.match(ui.logHistoryMarkup(h, 'all'), /Importing the available log files/);
  assert.doesNotMatch(ui.logHistoryMarkup(h, 'all'), /id="olderLogEntries" hidden/);
  h.catching_up = false; h.has_more = false;
  assert.match(ui.logHistoryMarkup(h, 'all'), /expire after 24 hours/);
  assert.match(ui.logHistoryMarkup(h, 'all'), /id="olderLogEntries" hidden/);
});
