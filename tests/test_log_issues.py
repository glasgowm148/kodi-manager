"""Synthetic cause grouping, legacy migration, reviews and update baselines."""
import sqlite3

import pytest

from kodi_manager.log_history import LogHistory
from kodi_manager.log_issues import describe_issue
from test_log_history import line


@pytest.fixture(name='history')
def grouped_history(tmp_path):
    clock = [1_800_000_000.0]
    logs = tmp_path / 'logs'
    logs.mkdir()
    return LogHistory(tmp_path / 'data/history.db', logs, lambda: clock[0]), logs, clock


def test_repeated_native_cause_spans_threads_and_pages_without_losing_entries(history):
    h, logs, clock = history
    (logs / 'kodi.log').write_text(''.join(line(clock[0] - i, 'error', 'Flush - timed out waiting for renderer to flush')
                                        .replace('T:123', 'T:' + str(i)) for i in range(40)))
    h.collect()
    first = h.snapshot(limit=3)
    issue = first['issues'][0]
    assert first['total'] == first['counts']['errors'] == issue['count'] == 40
    assert issue['first_seen'] == clock[0] - 39 and issue['last_seen'] == clock[0]
    assert issue['owner']['label'] == 'Kodi video renderer'
    assert first['issue_total'] == 1 and first['issues_ready']
    seen = list(first['entries'])
    while first['has_more']:
        first = h.snapshot(limit=3, before=first['next_before'], issue=issue['id'])
        assert first['issues'][0]['count'] == 40
        seen.extend(first['entries'])
    assert len({e['id'] for e in seen}) == 40


def test_review_and_version_baselines_preserve_old_events_and_ignore_old_imports(history):
    h, logs, clock = history
    h = LogHistory(h.path, logs, h.clock, version='1.0')
    path = logs / 'kodi.log'
    path.write_text(line(clock[0] - 10, 'error', 'failure'))
    h.collect()
    before = h.snapshot()
    issue = before['issues'][0]['id']
    assert before['issues'][0]['since_baseline'] == 0
    h.record_review(issue)
    assert h.snapshot()['issues'][0]['since_baseline'] == 0
    clock[0] += 2
    with path.open('a') as f:
        f.write(line(clock[0] - 20, 'error', 'failure'))  # late import predates the review
        f.write(line(clock[0], 'error', 'failure'))
    h.collect()
    after = h.snapshot()
    assert after['issues'][0]['count'] == after['counts']['errors'] == 3
    assert after['issues'][0]['since_baseline'] == 1
    assert after['tracking_started_at'] == before['tracking_started_at']
    assert before['entries'][0] in after['entries']
    restarted = LogHistory(h.path, logs, h.clock, version='2.0')
    restarted.collect()
    final = restarted.snapshot()
    assert final['recording_version']['version'] == '2.0'
    assert final['issues'][0]['reviewed_at'] == before['now']
    assert final['issues'][0]['since_baseline'] == 1  # per-issue review takes priority


def test_signed_urls_group_by_host_and_failure_but_samples_stay_masked(history):
    h, logs, clock = history
    path = logs / 'kodi.log'
    path.write_text(''.join(line(clock[0], 'error', 'CCurlFile::Stat - <https://cdn.example.invalid/m.mpd?__gda__=%s> Failed: HTTP response code said error(22)' % secret)
                            for secret in ('fixture-one', 'fixture-two')))
    h.collect()
    result = h.snapshot()
    assert result['issue_total'] == 1 and result['issues'][0]['count'] == 2
    assert 'fixture-one' not in str(result) and 'fixture-two' not in str(result)
    assert describe_issue('error: bad http://[broken')[1]['owner']['confidence'] == 'unknown'


def test_legacy_rows_are_grouped_in_bounded_batches_and_survive_migration(history):
    h, logs, clock = history
    with h.connect() as db:
        db.executemany('INSERT INTO events(source,generation,position,at,level,line) VALUES (?,?,?,?,?,?)',
                       [('old', 0, i, clock[0] - 1, 'warning', 'warning: legacy') for i in range(1001)])
    first = h.snapshot(limit=1)
    assert not first['issues_ready'] and first['counts']['warnings'] == 1001
    h.snapshot()
    final = h.snapshot()
    assert final['issues_ready'] and final['issues'][0]['count'] == 1001
    with sqlite3.connect(h.path) as db:
        assert db.execute('SELECT count(*),min(id),max(id) FROM events').fetchone() == (1001, 1, 1001)


def test_group_pagination_and_level_filter_cover_all_groups(history):
    h, logs, clock = history
    (logs / 'kodi.log').write_text(''.join(line(clock[0], 'error', 'failure-category-' + str(i)) for i in range(31))
                                 + line(clock[0], 'warning', 'separate warning'))
    h.collect()
    first = h.snapshot(level='error')
    second = h.snapshot(level='error', group_offset=25)
    assert first['issue_total'] == second['issue_total'] == 31
    assert first['groups_has_more'] and not second['groups_has_more']
    assert len({g['id'] for g in first['issues'] + second['issues']}) == 31


@pytest.mark.parametrize('kwargs', [{'issue': "' OR 1=1"}, {'group_offset': -1}, {'group_offset': 'wrong'}])
def test_invalid_issue_filters_are_rejected(history, kwargs):
    with pytest.raises(ValueError):
        history[0].snapshot(**kwargs)


def test_review_refuses_unknown_or_expired_issue(history):
    with pytest.raises(ValueError):
        history[0].record_review('0' * 32)
    with pytest.raises(ValueError):
        history[0].record_review('not-an-issue')
    first, native = describe_issue("warning: CPythonInvoker(4, /x/addons/plugin.video.fixture/default.py): script successfully run but left several classes in memory")
    second, _ = describe_issue("warning: CPythonInvoker(99, /x/addons/plugin.video.other/default.py): script successfully run but left several classes in memory")
    assert first != second and native['owner']['addon_id'] == 'plugin.video.fixture'
    _, missing = describe_issue("error: Unknown addon id 'plugin.video.disabled'")
    assert missing['owner']['confidence'] == 'referenced'


def test_recurrence_survives_retention_expiry_and_sqlite_row_id_reuse(history):
    h, logs, clock = history
    path = logs / 'kodi.log'
    path.write_text(line(clock[0], 'warning', 'fixture'))
    h.collect()
    h.record_review(h.snapshot()['issues'][0]['id'])
    clock[0] += 24 * 3600 + 1
    h.collect()
    with path.open('a') as f:
        f.write(line(clock[0], 'warning', 'fixture'))
    h.collect()
    result = h.snapshot()
    assert result['entries'][0]['id'] == 1  # SQLite reuses IDs when its table is empty
    assert result['issues'][0]['since_baseline'] == 1


def test_membership_is_rebuilt_when_an_older_collector_reuses_a_row_id(history):
    h, logs, clock = history
    (logs / 'kodi.log').write_text(line(clock[0], 'warning', 'first cause'))
    h.collect()
    original = h.snapshot()['issues'][0]['id']
    with h.connect() as db:
        db.execute('DELETE FROM events')
        db.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?)', (1, 'replacement', 1, 0, clock[0], 'warning', 'warning: another cause'))
    changed = h.snapshot()
    assert changed['issue_total'] == 1 and changed['issues'][0]['id'] != original


def test_update_totals_are_unfiltered_ignore_reviews_and_use_time_and_id(history):
    h, logs, clock = history
    path = logs / 'kodi.log'
    assert h.snapshot()['since_update_counts'] is None
    path.write_text(line(clock[0], 'error', 'old failure'))
    h.collect()
    h = LogHistory(h.path, logs, h.clock, version='2.0')
    h.collect()  # Existing event has the same timestamp but precedes the marker ID.
    with path.open('a') as f:
        f.write(line(clock[0] - 10, 'error', 'late old import'))
        f.write(line(clock[0], 'warning', 'new warning'))
    h.collect()
    snap = h.snapshot(level='error', limit=1)
    assert snap['since_update_counts'] == {'errors': 0, 'warnings': 1, 'notices': 0}
    assert snap['counts']['errors'] == 2
    assert snap['last_problem_at'] == clock[0]
    for issue in h.snapshot()['issues']:
        h.record_review(issue['id'])
    assert h.snapshot()['since_update_counts'] == snap['since_update_counts']
    clock[0] += 86401
    h.collect()
    expired = h.snapshot()
    assert expired['since_update_counts'] == {'errors': 0, 'warnings': 0, 'notices': 0}
    assert expired['last_problem_at'] is None
