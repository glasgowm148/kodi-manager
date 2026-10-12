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

test('issue cards escape advice, link the source, and distinguish review recurrence', () => {
  const g = {id:'a'.repeat(32), title:'<script>bad</script>', count:42, level:'warning', first_seen:1800000000,
    last_seen:1800000010, sample:'<img onerror="bad">', explanation:'A missing value', next_step:'Update <add-on>',
    owner:{addon_id:'plugin.video.fixture', label:'Fixture'}, reviewed_at:1800000001, baseline_at:1800000001, since_baseline:2};
  const html = ui.logIssueCards([g]);
  assert.doesNotMatch(html, /<script>|<img/);
  assert.match(html, /42 recorded entries/);
  assert.match(html, /First seen/); assert.match(html, /Last seen/);
  assert.match(html, /2 new entries since review/);
  assert.match(html, /#\/addon\/plugin.video.fixture/);
  assert.match(html, /issue=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/);
  assert.match(html, /data-review-issue="[a-f0-9]+" disabled/);
  g.since_baseline = 0;
  assert.match(ui.logIssueCards([g]), /No new entries since review/);
  delete g.reviewed_at;
  assert.match(ui.logIssueCards([g]), /before this recording baseline/);
});

test('incomplete grouping and group pagination are shown without hiding original entries', () => {
  const html = ui.logHistoryMarkup({issues_ready:false, issues:[], issue_total:50, groups_has_more:true,
    available:true, entries:[], recording_version:{version:'fixture-version', at:1800000000}}, 'all');
  assert.match(html, /Grouping older retained entries/);
  assert.match(html, /50 issue groups/);
  assert.doesNotMatch(html, /id="moreLogIssues" hidden/);
  assert.match(html, /Original retained entries/);
  assert.match(html, /fixture-version/);
});
