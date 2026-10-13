"""Cancellation within a file retains the previous destination and removes partial data."""
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/kodi_manager'))
import backup  # noqa: E402


def test_cancel_within_large_file_retains_existing_destination(tmp_path):
    source, target = tmp_path / 'large.db', tmp_path / 'saved.db'
    source.write_bytes(b'x' * (3 * 1024 * 1024))
    target.write_bytes(b'previous verified snapshot')
    calls = []

    def stop():
        calls.append(True)
        return len(calls) >= 3

    with pytest.raises(backup.BackupAborted):
        backup._copy_file(str(source), str(target), should_stop=stop)
    assert target.read_bytes() == b'previous verified snapshot'
    assert sorted(p.name for p in tmp_path.iterdir()) == ['large.db', 'saved.db']


def test_chunked_copy_preserves_data_and_metadata(tmp_path):
    source, target = tmp_path / 'source', tmp_path / 'target'
    payload = b'ab' * (1024 * 1024 + 10)
    source.write_bytes(payload)
    os.utime(source, (10000, 10000))
    backup._copy_file(str(source), str(target), should_stop=lambda: False)
    assert target.read_bytes() == payload
    assert target.stat().st_mtime == source.stat().st_mtime


def test_cancelled_traversal_does_not_begin_copy(tmp_path):
    source, target = tmp_path / 'source', tmp_path / 'target'
    source.mkdir()
    (source / 'file').write_bytes(b'data')
    with pytest.raises(backup.BackupAborted):
        backup._copytree(str(source), str(target), should_stop=lambda: True)
    assert not list(target.iterdir())
