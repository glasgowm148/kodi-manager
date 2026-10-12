"""Provider metadata must satisfy Kodi's non-null native API contract."""
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "kodi_manager"))
from kodi_compat import set_video_info  # noqa: E402


class Tag:
    def __init__(self):
        self.values = {}

    def __getattr__(self, name):
        def setter(value):
            assert value is not None, "Kodi warns about null native arguments"
            self.values[name] = value
        return setter


@pytest.mark.parametrize("native", [False, True])
def test_missing_metadata_is_omitted_without_losing_zero_or_empty_values(native):
    tag = Tag()
    fallback = {}
    item = SimpleNamespace(setInfo=lambda kind, values: fallback.update(values))
    if native:
        item.getVideoInfoTag = lambda: tag
    info = {"title": None, "plot": None, "year": None, "genre": None,
            "unknown": None, "playcount": 0, "tagline": "", "tvshowtitle": "Example"}
    original = dict(info)
    set_video_info(item, info)
    assert info == original
    if native:
        assert tag.values == {"setPlaycount": 0, "setTagLine": "", "setTvShowTitle": "Example"}
        assert fallback == {}
    else:
        assert fallback == {"playcount": 0, "tagline": "", "tvshowtitle": "Example"}


@pytest.mark.parametrize("native", [False, True])
def test_cast_null_strings_keep_the_cast_and_order(native):
    def actor(name, role, order, thumbnail):
        assert all(isinstance(value, str) for value in (name, role, thumbnail))
        return {"name": name, "role": role, "order": order, "thumbnail": thumbnail}

    tag = Tag()
    legacy = []
    item = SimpleNamespace(setCast=lambda values: legacy.extend(values))
    if native:
        item.getVideoInfoTag = lambda: tag
    cast = [{"name": "Example", "role": None, "thumbnail": None, "order": 0},
            {"name": None, "role": "Character", "order": 1}]
    originals = [dict(value) for value in cast]
    set_video_info(item, {}, cast=cast, actor=actor)
    result = tag.values["setCast"] if native else legacy
    assert result == [{"name": "Example", "role": "", "thumbnail": "", "order": 0},
                      {"name": "", "role": "Character", "thumbnail": "", "order": 1}]
    assert cast == originals
