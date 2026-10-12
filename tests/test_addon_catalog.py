"""Removal hints must stay conservative across disabled and dynamically loaded add-ons."""
from kodi_manager.addon_catalog import annotate_addons
from kodi_manager.addon_index import addon_xml_meta


def addon(aid, **values):
    return dict(addon_id=aid, name=aid, installed=True, enabled=True, **values)


def test_manifest_english_purpose_service_and_dependencies(tmp_path):
    (tmp_path / "addon.xml").write_text('''<addon id="plugin.video.example" name="[COLOR red]Example[/COLOR]" version="2">
      <requires><import addon="script.module.example" version="1" optional="true"/></requires>
      <extension point="xbmc.python.pluginsource"/><extension point="xbmc.service"/>
      <extension point="xbmc.addon.metadata"><summary lang="fr">Francais</summary>
        <summary lang="en_GB">[B]Browse[/B][CR]films</summary><description lang="en">More films.</description>
      </extension></addon>''', encoding="utf-8")
    meta = addon_xml_meta(str(tmp_path))
    assert meta["name"] == "Example"
    assert meta["summary"] == "Browse films"
    assert meta["description"] == "More films."
    assert meta["dependencies"] == [{"addonid": "script.module.example", "minversion": "1", "optional": True}]
    row = annotate_addons({meta["addon_id"]: dict(meta, installed=True, enabled=True)})[meta["addon_id"]]
    assert row["has_service"] is True
    assert row["purpose"] == "Browse films"


def test_disabled_and_optional_dependents_are_never_called_unused():
    rows = {"script.module.shared": addon("script.module.shared"),
            "plugin.video.disabled": dict(addon("plugin.video.disabled"), enabled=False,
                                          dependencies=[{"addonid": "script.module.shared", "optional": True}]),
            "plugin.video.active": addon("plugin.video.active", dependencies=[{"addon": "script.module.shared"}])}
    annotate_addons(rows)
    shared = rows["script.module.shared"]
    assert shared["cleanup"]["code"] == "dependency"
    assert len(shared["required_by"]) == 2
    assert shared["required_by"][1]["enabled"] is False
    assert shared["required_by"][1]["optional"] is True


def test_dynamic_libraries_repositories_and_unknown_state_need_usage_checks():
    ids = ["script.module.cocoscrapers", "repository.example", "plugin.video.unknown", "kodi.custom.example"]
    rows = {aid: addon(aid) for aid in ids}
    rows["repository.example"]["type"] = "xbmc.addon.repository"
    rows["plugin.video.unknown"]["enabled"] = None
    annotate_addons(rows)
    for row in rows.values():
        assert row["cleanup"]["code"] == "check_usage"
        assert "does not prove" in row["cleanup"]["detail"]
        assert row["has_service"] is None
    assert rows[ids[0]]["role"] == "library"
    assert rows[ids[1]]["role"] == "repository"
    assert rows[ids[3]]["role"] != "system"


def test_keep_builtin_active_skin_and_manager_even_when_disabled():
    rows = {"skin.example": dict(addon("skin.example"), enabled=False),
            "service.kodi.addonadmin": dict(addon("service.kodi.addonadmin"), enabled=False),
            "resource.language.en_gb": addon("resource.language.en_gb", builtin_addons_present=True),
            "xbmc.python": addon("xbmc.python"),
            "plugin.video.old": dict(addon("plugin.video.old"), enabled=False),
            "plugin.video.config": dict(addon("plugin.video.config"), installed=None, enabled=None)}
    annotate_addons(rows, "skin.example")
    for aid in list(rows)[:4]:
        assert rows[aid]["cleanup"]["code"] == "keep"
    assert rows["plugin.video.old"]["cleanup"]["code"] == "review_disabled"
    assert rows["plugin.video.config"]["cleanup"]["code"] == "config_only"
    assert "other profiles" in rows["plugin.video.old"]["cleanup"]["detail"]


def test_orphan_saved_config_does_not_block_an_installed_dependency():
    rows = {"script.module.shared": addon("script.module.shared"),
            "plugin.video.config": dict(addon("plugin.video.config"), installed=None,
                                        dependencies=[{"addonid": "script.module.shared"}])}
    annotate_addons(rows)
    assert rows["script.module.shared"]["required_by"] == []
