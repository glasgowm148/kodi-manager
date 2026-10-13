"""Nightly preparation cancels without replacing a valid add-on index."""
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/kodi_manager'))
import addon_index  # noqa: E402


def test_cancel_between_addons_keeps_previous_index(monkeypatch):
    index = addon_index.AddonIndex.__new__(addon_index.AddonIndex)
    index._lock = threading.RLock()
    index._clock = lambda: 100
    index._refreshed_at = 1
    index.addons = {'old': {'addon_id': 'old'}}
    index.probe = {'last': 'complete'}
    index.kodi = SimpleNamespace(list_addons=lambda: [{'addon_id': 'first'}, {'addon_id': 'second'}])
    stop, visited = threading.Event(), []

    def enrich(row, *args):
        visited.append(row['addon_id'])
        stop.set()
        return row

    monkeypatch.setattr(addon_index, 'enrich_addon', enrich)
    with pytest.raises(addon_index.IndexRefreshCancelled) as failure:
        index.refresh(force=True, should_stop=stop.is_set)
    assert failure.value.deferred is True
    assert visited == ['first']
    assert index.addons == {'old': {'addon_id': 'old'}}
    assert index.probe == {'last': 'complete'} and index._refreshed_at == 1
