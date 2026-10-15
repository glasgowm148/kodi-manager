"""Skin settings applied to the running skin after a restore, and Kodi's settings file saved
after protected Kodi settings are re-applied.

``split_exec`` is a line-by-line port of Kodi 22's SplitExecFunction (utils/ExecString.cpp) and
CUtil::SplitParams (Util.cpp), so the quoting is checked against what Kodi will actually parse.
"""
import json
import random
from types import SimpleNamespace

import pytest

from kodi_manager import backup, skin_settings
from kodi_manager.baseline import Baseline
from kodi_manager.skin_settings import apply_live, builtin_for, parse_skin_settings, quote_param


def split_params(param_string):
    in_quotes = False
    last_escaped = False
    in_function = 0
    white_space_pos = 0
    parameter = []
    parameters = []

    def unquote(p):
        if len(p) > 1 and p[0] == '"' and p[-1] == '"':
            return p[1:-1]
        if len(p) > 3 and p[-1] == '"':
            q = p.find('"')
            if 1 < q < len(p) - 1 and p[q - 1] == "=":
                return p[:q] + p[q + 1:-1]
        return p

    for pos, ch in enumerate(param_string):
        escaped = pos > 0 and param_string[pos - 1] == "\\" and not last_escaped
        last_escaped = escaped
        if in_quotes:
            if ch == '"' and not escaped:
                in_quotes = False
        else:
            if ch == '"' and not escaped:
                in_quotes = True
            if in_function and ch == ")":
                in_function -= 1
            if ch == "(":
                in_function += 1
            if not in_function and ch == ",":
                if white_space_pos:
                    del parameter[white_space_pos:]
                parameters.append(unquote("".join(parameter)))
                parameter = []
                white_space_pos = 0
                continue
        if ch in ('"', "\\") and escaped:
            parameter[-1] = ch
            continue
        if ch == " " and not in_quotes:
            if not parameter:
                continue
            if not white_space_pos:
                white_space_pos = len(parameter)
        else:
            white_space_pos = 0
        parameter.append(ch)
    if white_space_pos:
        del parameter[white_space_pos:]
    last = unquote("".join(parameter))
    if last or parameters:
        parameters.append(last)
    return parameters


def split_exec(exec_string):
    start, end = exec_string.find("("), exec_string.rfind(")")
    if start >= 0 and end >= 0:
        return exec_string[:start].strip().lower(), split_params(exec_string[start + 1:end])
    return exec_string.strip().lower(), []


NASTY = ['', 'plain', 'a,b', 'a, b', ' lead', 'trail ', '"', '""', '\\', '\\\\', 'C:\\path\\', 'x\\"y',
         'f(x)', ')', '(', 'a)b(c', '$INFO[ListItem.Label]', 'name="value"', 'k="v",w', 'ünïcødé ✓', 'a\\,b']


@pytest.mark.parametrize("value", NASTY)
def test_quoted_values_come_back_exactly(value):
    function, params = split_exec("Skin.SetString(%s,%s)" % (quote_param("home.label"), quote_param(value)))
    assert function == "skin.setstring" and params == ["home.label", value]


def test_quoting_survives_random_strings():
    rng = random.Random(22)
    alphabet = 'ab ,()"\\=$[]\'é'
    for _ in range(5000):
        value = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 12)))
        sid = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 6)))
        assert split_exec("Skin.SetString(%s,%s)" % (quote_param(sid), quote_param(value)))[1] == [sid, value]


class FakeSkinKodi:
    """Kodi's skin settings in memory, changed only through the Skin.* builtins as Kodi runs them."""

    def __init__(self, skin="skin.bingie", settings=None, supported=True, ignore=()):
        self.skin, self.supported, self.ignore = skin, supported, set(ignore)
        self.memory = dict(settings or {})   # name -> (type, value)
        self.builtins, self.saves = [], 0

    def _find(self, name):
        return next((k for k in self.memory if k.lower() == name.lower()), None)

    def jsonrpc(self, method, params=None):
        if method == "Settings.GetSkinSettings":
            if not self.supported:
                return {"error": {"code": -32601, "message": "Method not found."}}
            return {"result": {"skin": self.skin, "settings": [
                {"id": k, "type": "boolean" if t == "bool" else "string", "value": v} for k, (t, v) in self.memory.items()]}}
        raise AssertionError(method)

    def get_active_skin(self):
        return {"addon_id": self.skin}

    def execute_builtin(self, command):
        self.builtins.append(command)
        function, params = split_exec(command)
        name = params[0]
        if name in self.ignore:
            return True
        key = self._find(name) or name
        if function == "skin.setbool":
            self.memory[key] = ("bool", len(params) < 2 or params[1].lower() == "true")
        elif function == "skin.setstring":
            assert len(params) > 1, "one parameter opens the keyboard on the TV"
            self.memory[key] = ("string", params[1])
        elif function == "skin.reset":
            found = self._find(name)
            if found:   # CSkinInfo::Reset: an unknown name changes nothing
                self.memory[found] = (self.memory[found][0], False if self.memory[found][0] == "bool" else "")
        else:
            raise AssertionError(function)
        self.saves += 1   # every Skin.* builtin ends with CSettings::Save()
        return True


SETTINGS_XML = """<settings version="2">
  <setting id="home.widget1" type="string">plugin://x/?a=1,b=(2)</setting>
  <setting id="Show.Clock" type="bool">true</setting>
  <setting id="hide.rating" type="bool">false</setting>
  <setting id="blank" type="string"></setting>
  <setting name="legacy" type="string">old style</setting>
  <setting id="ignored" type="int">3</setting>
</settings>"""


def test_parse_reads_ids_types_and_the_old_name_attribute():
    assert parse_skin_settings(SETTINGS_XML) == {
        "home.widget1": ("string", "plugin://x/?a=1,b=(2)"), "Show.Clock": ("bool", True),
        "hide.rating": ("bool", False), "blank": ("string", ""), "legacy": ("string", "old style")}
    for bad in ("<settings>", "<other/>"):
        with pytest.raises(ValueError):
            parse_skin_settings(bad)


def test_apply_live_sets_changed_values_resets_extras_and_reads_back():
    kodi = FakeSkinKodi(settings={"home.widget1": ("string", "now"), "show.clock": ("bool", False),
                                  "hide.rating": ("bool", False), "added.later": ("string", "x"),
                                  "flag.later": ("bool", True)})
    result = apply_live(kodi, "skin.bingie", parse_skin_settings(SETTINGS_XML))
    assert result == {"status": "applied", "changed": 5, "failed": []}
    assert kodi.memory == {"home.widget1": ("string", "plugin://x/?a=1,b=(2)"), "show.clock": ("bool", True),
                           "hide.rating": ("bool", False), "added.later": ("string", ""),
                           "flag.later": ("bool", False), "legacy": ("string", "old style")}
    # An unchanged value is left alone, and "blank" (absent, default) needs no builtin.
    assert not any("hide.rating" in b or "blank" in b for b in kodi.builtins)
    again = apply_live(kodi, "skin.bingie", parse_skin_settings(SETTINGS_XML))
    assert again["changed"] == 0


def test_an_empty_string_is_reset_never_set_with_one_parameter():
    assert builtin_for("a", "string", "") == 'Skin.Reset("a")'
    kodi = FakeSkinKodi(settings={"a": ("string", "x")})
    assert apply_live(kodi, "skin.bingie", {"a": ("string", "")})["status"] == "applied"
    assert kodi.memory["a"] == ("string", "")


def test_a_value_kodi_did_not_take_is_reported():
    kodi = FakeSkinKodi(settings={"a": ("string", "x"), "b": ("bool", False)}, ignore={"b"})
    result = apply_live(kodi, "skin.bingie", {"a": ("string", "y"), "b": ("bool", True)})
    assert result == {"status": "partial", "changed": 2, "failed": ["b"]}


def test_another_skin_or_an_old_kodi_is_left_alone():
    kodi = FakeSkinKodi(skin="skin.estuary", settings={"a": ("string", "x")})
    assert apply_live(kodi, "skin.bingie", {"a": ("string", "y")})["status"] == "not_active"
    old = FakeSkinKodi(supported=False)
    assert apply_live(old, "skin.bingie", {"a": ("string", "y")})["status"] == "unsupported"
    assert kodi.builtins == old.builtins == []


@pytest.fixture
def storage(tmp_path, monkeypatch):
    root = tmp_path / "backups"
    root.mkdir()
    monkeypatch.setattr(backup, "backup_root", lambda: str(root))
    return tmp_path


def _routes(kodi, index=None):
    from kodi_manager import api_addons
    handler = api_addons.AddonRoutes.__new__(api_addons.AddonRoutes)
    handler.state = SimpleNamespace(kodi=kodi, index=index)
    return handler


def test_restoring_the_active_skin_applies_its_settings_to_the_running_skin(storage):
    live = storage / "skin.bingie"
    live.mkdir()
    (live / "settings.xml").write_text(SETTINGS_XML)
    info = {"addon_id": "skin.bingie", "addon_data_path": str(live)}
    snapshot = backup.create_backup(info)
    (live / "settings.xml").write_text('<settings version="2"><setting id="show.clock" type="bool">false</setting></settings>')
    kodi = FakeSkinKodi(settings={"show.clock": ("bool", False)})
    handler = _routes(kodi)
    result = backup.restore_backup(info, snapshot["backup_id"], after_restore=handler._apply_active_skin)
    assert result["live"]["skin_settings"]["status"] == "applied"
    assert kodi.memory["show.clock"] == ("bool", True)
    assert kodi.memory["home.widget1"] == ("string", "plugin://x/?a=1,b=(2)")
    # The stack restore does the same for the skin among its components.
    other = {"addon_id": "plugin.video.pov", "addon_data_path": str(storage / "pov")}
    (storage / "pov").mkdir()
    (storage / "pov" / "settings.xml").write_text("<settings/>")
    stack = backup.create_stack_backup([info, other])
    kodi.memory["show.clock"] = ("bool", False)
    index = SimpleNamespace(get={"skin.bingie": info, "plugin.video.pov": other}.get)
    result = backup.restore_stack_backup(index, stack["backup_id"], after_restore=handler._apply_active_skin)
    assert result["live"]["skin_settings"]["status"] == "applied" and kodi.memory["show.clock"] == ("bool", True)


def test_restoring_another_add_on_does_not_touch_the_skin(storage):
    live = storage / "pov"
    live.mkdir()
    (live / "settings.xml").write_text("<settings/>")
    info = {"addon_id": "plugin.video.pov", "addon_data_path": str(live)}
    snapshot = backup.create_backup(info)
    kodi = FakeSkinKodi(settings={"a": ("string", "x")})
    result = backup.restore_backup(info, snapshot["backup_id"], after_restore=_routes(kodi)._apply_active_skin)
    assert "live" not in result and kodi.builtins == []


def test_a_failing_live_apply_is_reported_and_the_restore_stands(storage):
    live = storage / "skin.bingie"
    live.mkdir()
    (live / "settings.xml").write_text("<settings><broken")
    info = {"addon_id": "skin.bingie", "addon_data_path": str(live)}
    snapshot = backup.create_backup(info)
    (live / "settings.xml").write_text("<settings/>")
    result = backup.restore_backup(info, snapshot["backup_id"], after_restore=_routes(FakeSkinKodi())._apply_active_skin)
    assert result["restored"] is True and result["live"]["error"] == "ValueError"
    assert (live / "settings.xml").read_text() == "<settings><broken"


# --- protected Kodi settings: save guisettings.xml after re-applying ----------------------

class CoreKodi:
    def __init__(self, guisettings, save_works=True):
        self.guisettings, self.save_works = guisettings, save_works
        self.memory = {"videoplayer.seekdelay": 750, "subtitles.height": 2.0}
        self.builtins = []

    def jsonrpc(self, method, params=None):
        if method == "Settings.GetSettingValue":
            return {"result": {"value": self.memory[params["setting"]]}}
        if method == "Settings.SetSettingValue":
            self.memory[params["setting"]] = params["value"]
            return {"result": True}
        raise AssertionError(method)

    def execute_builtin(self, command):
        self.builtins.append(command)
        function, params = split_exec(command)
        assert function == "skin.reset" and params == [skin_settings.SAVE_SENTINEL]
        if self.save_works:
            self.guisettings.write_text('<settings version="2">%s</settings>' % "".join(
                '<setting id="%s">%s</setting>' % (k, ("%.6f" % v) if isinstance(v, float) else v)
                for k, v in self.memory.items()))
        return True


def _baseline(tmp_path, kodi):
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"version": 1, "items": [
        {"kind": "kodi_setting", "id": "videoplayer.seekdelay", "value": 500},
        {"kind": "kodi_setting", "id": "subtitles.height", "value": 3}]}))
    return Baseline(str(path), kodi, guisettings=str(tmp_path / "guisettings.xml"))


def test_reapplying_kodi_settings_saves_guisettings_and_reads_it_back(tmp_path):
    kodi = CoreKodi(tmp_path / "guisettings.xml")
    result = _baseline(tmp_path, kodi).apply()
    assert result["applied"] == ["kodi:videoplayer.seekdelay", "kodi:subtitles.height"]
    assert result["core_saved"] is True and len(kodi.builtins) == 1


def test_an_unsaved_guisettings_is_reported(tmp_path):
    (tmp_path / "guisettings.xml").write_text('<settings><setting id="videoplayer.seekdelay">750</setting></settings>')
    kodi = CoreKodi(tmp_path / "guisettings.xml", save_works=False)
    assert _baseline(tmp_path, kodi).apply()["core_saved"] is False


def test_nothing_reapplied_means_no_save(tmp_path):
    kodi = CoreKodi(tmp_path / "guisettings.xml")
    kodi.memory.update({"videoplayer.seekdelay": 500, "subtitles.height": 3})
    result = _baseline(tmp_path, kodi).apply()
    assert "core_saved" not in result and kodi.builtins == []
