import os
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock
import xml.etree.ElementTree as ET

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src", "kodi_manager"))
import skin_layout as layout


class Kodi:
    def get_active_skin(self):
        return {"addon_id": "skin.bingie", "version": "2.0.2"}

    def jsonrpc(self, method, params):
        return {"result": {"files": []}}


class Index:
    def __init__(self, path):
        self.addons = {"skin.bingie": {"path": path, "version": "2.0.2"},
                       "script.skinshortcuts": {"path": path, "addon_data_path": path, "version": "2.0.3"},
                       "plugin.video.test": {"installed": True, "enabled": True},
                       "service.kodi.addonadmin": {"path": path, "installed": True, "enabled": True}}

    def refresh(self):
        pass

    def get(self, aid):
        return self.addons.get(aid)


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = self.temp.name
        self.kodi, self.index = Kodi(), Index(self.root)
        self.main = b'<shortcuts><!-- retain comment --><shortcut><label>Movies</label><action>ActivateWindow(1111,return)</action><extra>keep</extra></shortcut></shortcuts>'
        self.put("skin.bingie-mainmenu.DATA.xml", self.main)
        self.put("skin.bingie.properties", b"[['mainmenu','movies','widgetstyle','landscape']]")
        self.body = {"label": "Kids", "rows": [{"label": "Latest kids movies", "path": "plugin://plugin.video.test/?info=family&sort=latest"}]}
        self.verified = patch.object(layout, "_verify_sources")
        self.verified.start()
        self.addCleanup(self.verified.stop)

    def general_fixture(self):
        os.makedirs(os.path.join(self.root, '1080i'), exist_ok=True)
        os.makedirs(os.path.join(self.root, 'shortcuts'), exist_ok=True)
        self.put('1080i/IncludesHomeBingie.xml', b'<includes><include condition="Window.IsActive(1111)">skinshortcuts-template-moviehub</include><include condition="Window.IsActive(1113)">skinshortcuts-template-customhub</include></includes>')
        self.put('shortcuts/template.xml', b'<template><submenu name="moviehub"><property name="widgetPath" attribute="name|list"/></submenu><submenu name="customhub"><property name="widgetPath" attribute="name|list"/></submenu></template>')
        self.put('skin.bingie-moviehub.DATA.xml', b'<shortcuts><!-- keep --><shortcut><label>Trending</label><action>ActivateWindow(Videos,"plugin://plugin.video.test/?info=trending&amp;reload=$INFO[Window(Home).Property(reload)]",return)</action><extra>retain</extra></shortcut><shortcut><label>Popular</label><action>ActivateWindow(Videos,"plugin://plugin.program.shortcutmanager/?action=open_group&amp;file=Movies.json",return)</action></shortcut></shortcuts>')
        self.put('skin.bingie.properties', b"[['moviehub','trending','widgetstyle','landscape'],['moviehub','popular','widgetstyle','poster'],['other','keep','sort','random']]")
        self.section = next(s for s in layout.inspect_layout(self.kodi, self.index)['sections'] if s['id'] == 'hub:moviehub')
        return {'section_id': 'hub:moviehub', 'rows': self.section['rows'], 'expected_revision': layout.inspect_layout(self.kodi, self.index)['revision']}

    def put(self, name, data):
        with open(os.path.join(self.root, name), "wb") as handle:
            handle.write(data)

    def repurpose_fixture(self):
        from widget_plugin import family_directory_url
        self.general_fixture()
        self.put('1080i/IncludesHomeBingie.xml', self.read('1080i/IncludesHomeBingie.xml').replace(b'</includes>', b'<include condition="Window.IsActive(1112)">skinshortcuts-template-newhub</include></includes>'))
        self.put('shortcuts/template.xml', self.read('shortcuts/template.xml').replace(b'</template>', b'<submenu name="newhub"><property name="widgetPath" attribute="name|list"/></submenu></template>'))
        self.put('skin.bingie-mainmenu.DATA.xml', self.main.replace(b'<shortcuts>', b'<shortcuts custom="retain">').replace(b'</shortcuts>', b'<shortcut custom="menu"><defaultID>31227</defaultID><label>$SKIN[31227|skin.bingie|None]</label><action>ActivateWindow(1112,return)</action><disabled>True</disabled><extra>keep</extra></shortcut></shortcuts>'))
        self.put('skin.bingie-newhub.DATA.xml', ('<shortcuts custom="hub"><!-- keep --><extra>hub</extra>' + ''.join('<shortcut><label>$VAR[DefNewHub%sName]</label><action>$VAR[DefNewHub%sContent]</action></shortcut>' % (suffix, suffix) for suffix in ('', '1', '2', '3')) + '</shortcuts>').encode())
        self.put('skin.bingie-31227.DATA.xml', b'<shortcuts><shortcut><label>Old submenu</label><action>noop</action></shortcut></shortcuts>')
        self.put('skin.bingie-31227-1.DATA.xml', b'<shortcuts />')
        self.put('skin.bingie.properties', b"[['newhub','var-defnewhubname','icon','old'],['newhub','unrelated','extra','keep'],['mainmenu','31227','icon','shortcuts/new.png'],['31227','oldsubmenu','style','keep'],['31227.1','widget','extra','keep'],['other','keep','sort','random']]")
        self.put('addon.xml', b'<addon id="service.kodi.addonadmin"><extension point="xbmc.python.pluginsource" library="resources/lib/widget_plugin.py"><provides>video</provides></extension></addon>')
        return {'section_id': 'hub:newhub', 'operation': 'repurpose', 'label': 'Kids', 'rows': [
            {'label': 'Family row %s' % i, 'path': family_directory_url('plugin://plugin.video.test/?info=family&list=%s' % i, '12A', True)} for i in range(6)]}

    def read(self, name):
        with open(os.path.join(self.root, name), "rb") as handle:
            return handle.read()

    def home_fixture(self):
        self.general_fixture()
        self.put('1080i/IncludesHomeBingie.xml', self.read('1080i/IncludesHomeBingie.xml').replace(b'</includes>', b'<include condition="Window.IsActive(Home)">skinshortcuts-template-Widgets</include></includes>'))
        self.put('shortcuts/template.xml', self.read('shortcuts/template.xml').replace(b'</template>', b'<submenuOther include="Widgets" level="1"><property name="widgetPath" attribute="name|list"/><property name="widgetName" tag="label"/></submenuOther></template>'))
        self.put('skin.bingie-mainmenu.DATA.xml', b'<shortcuts><shortcut><label>10000</label><label2>Home</label2><defaultID>10000</defaultID><action>ActivateWindow(home,return)</action></shortcut><shortcut><label>Movies</label><action>ActivateWindow(1111,return)</action></shortcut></shortcuts>')
        self.put('skin.bingie-10000-1.DATA.xml', b'<shortcuts custom="retain"><!-- home rows --><shortcut custom="first"><label>First</label><action>ActivateWindow(Videos,$VAR[HomeContent],return)</action><extra>keep</extra></shortcut><shortcut><label>Second</label><action>ActivateWindow(Videos,special://videoplaylists/,return)</action></shortcut></shortcuts>')
        self.put('skin.bingie-10000.DATA.xml', b'<shortcuts><shortcut><label>Linked submenu</label><action>noop</action></shortcut></shortcuts>')
        self.put('skin.bingie.properties', b"[['10000.1','first','widgetstyle','landscape'],['10000.1','second','limit','25'],['10000','submenu','style','keep'],['mainmenu','10000','icon','home.png'],['moviehub','trending','widgetstyle','poster']]")
        state = layout.inspect_layout(self.kodi, self.index)
        home = next(section for section in state['sections'] if section['window'] == 'home')
        return home, {'section_id': home['id'], 'rows': home['rows'], 'expected_revision': state['revision']}

    def ready(self):
        self.body["expected_revision"] = layout.preview_layout(self.kodi, self.index, self.body)["revision"]

    def test_apply_preserves_movies_comments_properties_and_backs_up(self):
        properties = self.read("skin.bingie.properties")
        self.ready()
        result = layout.apply_layout(self.kodi, self.index, self.body, True)
        menu = self.read("skin.bingie-mainmenu.DATA.xml")
        self.assertIn(self.main[:-12], menu)
        self.assertIn(b"ActivateWindow(1113,return)", menu)
        self.assertEqual(properties, self.read("skin.bingie.properties"))
        backup = os.path.join("kodi-manager-backups", result["backup_id"])
        self.assertEqual(self.main, self.read(os.path.join(backup, "skin.bingie-mainmenu.DATA.xml")))
        hub = ET.fromstring(self.read("skin.bingie-customhub.DATA.xml"))
        self.assertEqual("ActivateWindow(Videos,%s,return)" % self.body["rows"][0]["path"], hub.findtext("shortcut/action"))
        self.assertTrue(result["rebuild_required"])

    def test_conflict_does_not_write(self):
        self.ready()
        self.put("skin.bingie.properties", b"[]")
        with self.assertRaisesRegex(ValueError, "changed since preview"):
            layout.apply_layout(self.kodi, self.index, self.body, True)
        self.assertEqual(self.main, self.read("skin.bingie-mainmenu.DATA.xml"))

    def test_occupied_hub_requires_explicit_replacement(self):
        self.put("skin.bingie-customhub.DATA.xml", b'<shortcuts><shortcut><label>Existing row</label><action>plugin://plugin.video.test/</action></shortcut></shortcuts>')
        preview = layout.preview_layout(self.kodi, self.index, self.body)
        self.assertFalse(preview["can_apply"])
        self.assertEqual("Existing row", preview["customhub"][0]["label"])
        self.body["replace_customhub"] = True
        self.assertTrue(layout.preview_layout(self.kodi, self.index, self.body)["can_apply"])

    def test_another_menu_customhub_cannot_be_replaced(self):
        self.put("skin.bingie-mainmenu.DATA.xml", b'<shortcuts><shortcut><label>Music</label><action>ActivateWindow(1113,return)</action></shortcut></shortcuts>')
        self.body["replace_customhub"] = True
        self.assertFalse(layout.preview_layout(self.kodi, self.index, self.body)["can_apply"])

    def test_unverified_schema_is_export_only(self):
        with patch.object(layout, "_verify_sources", side_effect=ValueError("Different schema")):
            preview = layout.preview_layout(self.kodi, self.index, self.body)
            self.assertFalse(preview["can_apply"])
            self.assertEqual(2, len(preview["exports"]))
            with self.assertRaisesRegex(ValueError, "Different schema"):
                layout.apply_layout(self.kodi, self.index, self.body, True)

    def test_unknown_version_write_disabled_and_bad_path_rejected(self):
        self.index.addons["script.skinshortcuts"]["version"] = "3.0.0"
        self.assertFalse(layout.inspect_layout(self.kodi, self.index)["can_apply"])
        with self.assertRaisesRegex(ValueError, "disabled"):
            layout.apply_layout(self.kodi, self.index, self.body, False)
        for path in ["../file", "special://profile/", "plugin://test/?x=),RunScript(evil)"]:
            self.body["rows"][0]["path"] = path
            with self.assertRaises(ValueError):
                layout.preview_layout(self.kodi, self.index, self.body)

    def test_source_listing_failure_does_not_write(self):
        self.ready()
        with patch.object(self.kodi, "jsonrpc", return_value={"error": {"message": "not directory"}}):
            with self.assertRaisesRegex(ValueError, "source could not be verified"):
                layout.apply_layout(self.kodi, self.index, self.body, True)
        self.assertEqual(self.main, self.read("skin.bingie-mainmenu.DATA.xml"))

    def test_second_write_failure_rolls_back_first(self):
        self.ready()
        atomic = layout._atomic
        target = os.path.join(os.path.realpath(self.root), "skin.bingie-customhub.DATA.xml")

        def failing(path, raw):
            if path == target:
                raise OSError("simulated write failure")
            return atomic(path, raw)

        with patch.object(layout, "_atomic", side_effect=failing):
            with self.assertRaisesRegex(OSError, "simulated"):
                layout.apply_layout(self.kodi, self.index, self.body, True)
        self.assertEqual(self.main, self.read("skin.bingie-mainmenu.DATA.xml"))
        self.assertFalse(os.path.exists(target))

    def test_manager_wrapper_requires_video_extension_and_valid_source(self):
        from widget_plugin import family_directory_url
        wrapper = family_directory_url('plugin://plugin.video.test/?info=family', '12A', True)
        self.body['rows'][0]['path'] = wrapper
        self.ready()
        with self.assertRaises(ValueError):
            layout.apply_layout(self.kodi, self.index, self.body, True)
        self.put('addon.xml', b'<addon id="service.kodi.addonadmin"><extension point="xbmc.python.pluginsource" library="resources/lib/widget_plugin.py"><provides>video</provides></extension></addon>')
        result = layout.apply_layout(self.kodi, self.index, self.body, True)
        self.assertTrue(result['applied'])
        layout._validate_destination(self.index, wrapper)
        with self.assertRaises(ValueError):
            layout._validate_destination(self.index, family_directory_url('plugin://plugin.video.test/?info=play'))

    def test_apply_rejects_action_route_before_rpc_or_writes(self):
        self.body['rows'][0]['path'] = 'plugin://plugin.video.test/?mode=play_media'
        self.ready()
        with patch.object(self.kodi, 'jsonrpc') as rpc:
            with self.assertRaisesRegex(ValueError, 'action endpoints'):
                layout.apply_layout(self.kodi, self.index, self.body, True)
            rpc.assert_not_called()
        self.assertEqual(self.main, self.read('skin.bingie-mainmenu.DATA.xml'))

    def test_general_inspection_maps_actual_sections_and_home_widgets(self):
        self.general_fixture()
        self.put('skin.bingie-mainmenu.DATA.xml', b'<shortcuts><shortcut><label>10000</label><label2>Home</label2><action>ActivateWindow(home,return)</action></shortcut><shortcut><label>Favorites</label><action>ActivateWindow(1113,return)</action></shortcut></shortcuts>')
        self.put('skin.bingie-10000-1.DATA.xml', b'<shortcuts><shortcut><label>Home row</label><action>ActivateWindow(Videos,plugin://plugin.video.test/?info=popular,return)</action></shortcut></shortcuts>')
        self.put('skin.bingie-customhub.DATA.xml', b'<shortcuts><shortcut><label>Favorite movies</label><action>ActivateWindow(Videos,plugin://plugin.video.test/?info=favorites,return)</action></shortcut></shortcuts>')
        state = layout.inspect_layout(self.kodi, self.index)
        favorites = next(s for s in state['sections'] if s['id'] == 'hub:customhub')
        home = next(s for s in state['sections'] if s['window'] == 'home')
        self.assertEqual(favorites['label'], 'Favorites')
        self.assertEqual(favorites['window'], 1113)
        self.assertEqual(home['rows'][0]['label'], 'Home row')
        self.assertFalse(home['editable'])
        self.assertTrue(home['limitations'])
        self.assertTrue(all(section['can_rename'] is False for section in state['sections']))
        self.assertTrue(state['customhub_occupied'])

    def test_general_rename_reorder_preserves_original_actions_and_properties(self):
        import ast
        body = self.general_fixture()
        first, second = body['rows']
        first = dict(first, label='Fresh')
        body['rows'] = [second, first]
        preview = layout.preview_layout(self.kodi, self.index, body)
        self.assertTrue(preview['can_apply'])
        self.assertEqual([e['filename'] for e in preview['exports']], ['skin.bingie-moviehub.DATA.xml', 'skin.bingie.properties'])
        with patch.object(self.kodi, 'jsonrpc') as rpc:
            layout.apply_layout(self.kodi, self.index, body, True)
            rpc.assert_not_called()  # Unchanged dynamic/unknown sources are never executed.
        nodes = ET.fromstring(self.read('skin.bingie-moviehub.DATA.xml')).findall('shortcut')
        self.assertEqual([n.findtext('label') for n in nodes], ['Popular', 'Fresh'])
        self.assertEqual(nodes[1].findtext('action'), first['action'])
        self.assertEqual(nodes[1].findtext('extra'), 'retain')
        self.assertIn(b'<!-- keep -->', self.read('skin.bingie-moviehub.DATA.xml'))
        props = ast.literal_eval(self.read('skin.bingie.properties').decode())
        self.assertIn(['moviehub', 'fresh', 'widgetstyle', 'landscape'], props)
        self.assertIn(['other', 'keep', 'sort', 'random'], props)
        self.assertEqual(self.main, self.read('skin.bingie-mainmenu.DATA.xml'))

    def test_verified_home_rename_reorder_preserves_menu_identity_native_actions_and_level_properties(self):
        import ast
        home, body = self.home_fixture()
        self.assertTrue(home['supported'])
        self.assertTrue(home['editable'])
        self.assertFalse(home['can_rename'])
        self.assertEqual(home['id'], 'home:10000.1')
        self.assertEqual(home['group'], '10000.1')
        self.assertEqual(home['provenance']['filename'], 'skin.bingie-10000-1.DATA.xml')
        before = {name: self.read(name) for name in ('skin.bingie-mainmenu.DATA.xml', 'skin.bingie-10000.DATA.xml', 'skin.bingie-moviehub.DATA.xml')}
        first, second = body['rows']
        body['rows'] = [second, dict(first, label='Fresh')]
        preview = layout.preview_layout(self.kodi, self.index, body)
        self.assertTrue(preview['can_apply'])
        self.assertEqual([item['filename'] for item in preview['exports']], ['skin.bingie-10000-1.DATA.xml', 'skin.bingie.properties'])
        with patch.object(self.kodi, 'jsonrpc') as rpc:
            layout.apply_layout(self.kodi, self.index, body, True)
            rpc.assert_not_called()
        nodes = ET.fromstring(self.read('skin.bingie-10000-1.DATA.xml')).findall('shortcut')
        self.assertEqual([node.findtext('label') for node in nodes], ['Second', 'Fresh'])
        self.assertEqual(nodes[1].findtext('action'), first['action'])
        self.assertEqual(nodes[1].findtext('extra'), 'keep')
        self.assertIn(b'<!-- home rows -->', self.read('skin.bingie-10000-1.DATA.xml'))
        props = ast.literal_eval(self.read('skin.bingie.properties').decode())
        self.assertIn(['10000.1', 'fresh', 'widgetstyle', 'landscape'], props)
        self.assertIn(['10000.1', 'second', 'limit', '25'], props)
        self.assertIn(['10000', 'submenu', 'style', 'keep'], props)
        self.assertIn(['mainmenu', '10000', 'icon', 'home.png'], props)
        self.assertIn(['moviehub', 'trending', 'widgetstyle', 'poster'], props)
        for name, original in before.items():
            self.assertEqual(self.read(name), original)

    def test_home_add_and_remove_rows_only_changes_home_owned_properties(self):
        import ast
        home, body = self.home_fixture()
        body['rows'] = [body['rows'][1], {'label': 'New row', 'path': 'plugin://plugin.video.test/?info=family'}]
        with patch.object(self.kodi, 'jsonrpc', return_value={'result': {'files': []}}) as rpc:
            layout.apply_layout(self.kodi, self.index, body, True)
            rpc.assert_called_once()
            self.assertEqual(rpc.call_args.args[0], 'Files.GetDirectory')
        nodes = ET.fromstring(self.read('skin.bingie-10000-1.DATA.xml')).findall('shortcut')
        self.assertEqual([node.findtext('label') for node in nodes], ['Second', 'New row'])
        props = ast.literal_eval(self.read('skin.bingie.properties').decode())
        self.assertFalse(any(p[0] == '10000.1' and p[1] == 'first' for p in props))
        self.assertIn(['10000.1', 'second', 'limit', '25'], props)
        self.assertIn(['mainmenu', '10000', 'icon', 'home.png'], props)

    def test_home_stays_readonly_without_template_binding_or_verified_sources(self):
        self.home_fixture()
        self.put('shortcuts/template.xml', self.read('shortcuts/template.xml').replace(b'include="Widgets" level="1"', b'include="Widgets" level="2"'))
        home = next(section for section in layout.inspect_layout(self.kodi, self.index)['sections'] if section['window'] == 'home')
        self.assertFalse(home['supported'])
        self.assertFalse(home['editable'])
        self.assertTrue(any('template' in reason for reason in home['reasons']))
        self.home_fixture()
        with patch.object(layout, '_verify_sources', side_effect=ValueError('Unreviewed source')):
            home = next(section for section in layout.inspect_layout(self.kodi, self.index)['sections'] if section['window'] == 'home')
            self.assertFalse(home['editable'])
            self.assertIn('Unreviewed source', home['reasons'])

    def test_menu_order_disabled_shared_hubs_and_widget_labels_are_distinct(self):
        self.general_fixture()
        self.put('skin.bingie-mainmenu.DATA.xml', b'<shortcuts><shortcut><label>Home</label><action>ActivateWindow(home,return)</action></shortcut><shortcut><label>Movies</label><action>ActivateWindow(1111,return)</action></shortcut><shortcut><label>New Popular</label><action>ActivateWindow(1111, return)</action><disabled>True</disabled></shortcut><shortcut><label>Favorites</label><action>ActivateWindow(1113,return)</action></shortcut></shortcuts>')
        self.put('skin.bingie-customhub.DATA.xml', b'<shortcuts><shortcut><label>Recently Watched - Movies</label><action>ActivateWindow(Videos,plugin://plugin.video.test/?info=recent,return)</action></shortcut></shortcuts>')
        state = layout.inspect_layout(self.kodi, self.index)
        entries = state['menu_entries']
        self.assertEqual([entry['label'] for entry in entries], ['Home', 'Movies', 'New Popular', 'Favorites'])
        self.assertEqual([entry['order'] for entry in entries], list(range(4)))
        self.assertTrue(entries[2]['disabled'])
        self.assertEqual(entries[1]['target_section_id'], entries[2]['target_section_id'])
        self.assertTrue(entries[1]['shared'])
        movies = next(s for s in state['sections'] if s['id'] == 'hub:moviehub')
        self.assertTrue(movies['active'])
        self.assertFalse(movies['disabled'])
        self.assertFalse(any(s['label'] == 'Recently Watched - Movies' for s in state['sections']))
        self.assertEqual(state['hub_capabilities']['custom_hub_count'], 1)
        self.assertFalse(state['new_section_available'])

    def test_inactive_hubs_are_separate_and_directory_destinations_preview_original(self):
        self.general_fixture()
        self.put('skin.bingie-mainmenu.DATA.xml', b'<shortcuts><shortcut><label>New Popular</label><action>ActivateWindow(1111,return)</action><disabled>True</disabled></shortcut><shortcut><label>iPlayer</label><action>ActivateWindow(Videos,"plugin://plugin.video.test",return)</action><disabled>True</disabled></shortcut><shortcut><label>Same destination</label><action>ActivateWindow(Videos,"plugin://plugin.video.test",return)</action></shortcut></shortcuts>')
        state = layout.inspect_layout(self.kodi, self.index)
        inactive = {s['id']: s for s in state['inactive_sections']}
        self.assertTrue(inactive['hub:moviehub']['disabled'])
        self.assertFalse(inactive['hub:customhub']['in_menu'])
        first, second = state['menu_entries'][1:]
        self.assertEqual(first['kind'], 'destination')
        self.assertEqual(first['target_section_id'], second['target_section_id'])
        destinations = [s for s in state['sections'] if s['kind'] == 'destination']
        self.assertEqual(len(destinations), 1)
        self.assertEqual(destinations[0]['rows'][0]['path'], 'plugin://plugin.video.test')
        self.assertTrue(destinations[0]['active'])
        self.assertFalse(destinations[0]['disabled'])
        self.assertEqual(destinations[0]['label'], 'Same destination')
        self.assertFalse(destinations[0]['editable'])

    def test_per_menu_submenu_and_home_widget_sources_keep_provenance(self):
        self.general_fixture()
        self.put('skin.bingie-movies.DATA.xml', b'<shortcuts><shortcut><label>Submenu item</label><action>ActivateWindow(Videos,plugin://plugin.video.test/?info=submenu,return)</action></shortcut></shortcuts>')
        self.put('skin.bingie-movies-1.DATA.xml', b'<shortcuts><shortcut><label>Home widget</label><action>ActivateWindow(Videos,plugin://plugin.video.test/?info=home,return)</action></shortcut></shortcuts>')
        entry = layout.inspect_layout(self.kodi, self.index)['menu_entries'][0]
        self.assertEqual(entry['submenu_rows'][0]['label'], 'Submenu item')
        self.assertEqual(entry['home_widget_rows'][0]['label'], 'Home widget')
        self.assertEqual(entry['home_widget_provenance']['filename'], 'skin.bingie-movies-1.DATA.xml')
        self.assertEqual(entry['submenu_provenance']['source'], 'user')

    def test_repurpose_renames_enables_only_disabled_hub_and_migrates_identity(self):
        import ast
        body = self.repurpose_fixture()
        movies = self.read('skin.bingie-moviehub.DATA.xml')
        old_linked = self.read('skin.bingie-31227.DATA.xml')
        preview = layout.preview_layout(self.kodi, self.index, body)
        self.assertTrue(preview['can_apply'])
        self.assertEqual(len(preview['menu_identity_migrations']), 2)
        body['expected_revision'] = preview['revision']
        with patch.object(self.kodi, 'jsonrpc', wraps=self.kodi.jsonrpc) as rpc:
            result = layout.apply_layout(self.kodi, self.index, body, True)
        self.assertEqual(rpc.call_count, 6)
        self.assertTrue(all(call.args[1]['directory'].startswith('plugin://service.kodi.addonadmin/') for call in rpc.call_args_list))
        main = ET.fromstring(self.read('skin.bingie-mainmenu.DATA.xml'))
        self.assertEqual(main.get('custom'), 'retain')
        movie, kids = main.findall('shortcut')
        self.assertEqual(movie.findtext('label'), 'Movies')
        self.assertEqual(kids.findtext('label'), 'Kids')
        self.assertIsNone(kids.find('disabled'))
        self.assertEqual(kids.findtext('action'), 'ActivateWindow(1112,return)')
        self.assertEqual(kids.findtext('extra'), 'keep')
        hub = ET.fromstring(self.read('skin.bingie-newhub.DATA.xml'))
        self.assertEqual(hub.get('custom'), 'hub')
        self.assertEqual(hub.findtext('extra'), 'hub')
        self.assertEqual(len(hub.findall('shortcut')), 6)
        self.assertEqual(self.read('skin.bingie-moviehub.DATA.xml'), movies)
        self.assertEqual(self.read('skin.bingie-kids.DATA.xml'), old_linked)
        self.assertFalse(os.path.exists(os.path.join(self.root, 'skin.bingie-31227.DATA.xml')))
        props = ast.literal_eval(self.read('skin.bingie.properties').decode())
        self.assertIn(['mainmenu', 'kids', 'icon', 'shortcuts/new.png'], props)
        self.assertIn(['kids.1', 'widget', 'extra', 'keep'], props)
        self.assertIn(['newhub', 'unrelated', 'extra', 'keep'], props)
        self.assertFalse(any(p[0] == 'newhub' and p[1].startswith('var-defnewhub') for p in props))
        self.assertEqual(self.read(os.path.join('kodi-manager-backups', result['backup_id'], 'skin.bingie-31227.DATA.xml')), old_linked)

    def test_repurpose_rejects_active_shared_wrong_hub_and_unfiltered_rows(self):
        body = self.repurpose_fixture()
        original = self.read('skin.bingie-mainmenu.DATA.xml')
        for menu in [original.replace(b'<disabled>True</disabled>', b''), original.replace(b'</shortcuts>', b'<shortcut><label>Another</label><action>ActivateWindow(1112,return)</action></shortcut></shortcuts>')]:
            self.put('skin.bingie-mainmenu.DATA.xml', menu)
            with self.assertRaisesRegex(ValueError, 'exactly one disabled'):
                layout.preview_layout(self.kodi, self.index, body)
        self.put('skin.bingie-mainmenu.DATA.xml', original)
        with self.assertRaisesRegex(ValueError, 'only the verified'):
            layout.preview_layout(self.kodi, self.index, dict(body, section_id='hub:moviehub'))
        with self.assertRaisesRegex(ValueError, 'persistent'):
            layout.preview_layout(self.kodi, self.index, dict(body, rows=[dict(r, path='plugin://plugin.video.test/?info=family') for r in body['rows']]))
        self.put('skin.bingie-newhub.DATA.xml', b'<shortcuts><shortcut><label>Changed</label><action>noop</action></shortcut></shortcuts>')
        with self.assertRaisesRegex(ValueError, 'four known default'):
            layout.preview_layout(self.kodi, self.index, body)

    def test_repurpose_linked_collision_and_revision_conflict_do_not_write(self):
        body = self.repurpose_fixture()
        self.put('skin.bingie-kids-1.DATA.xml', b'<shortcuts />')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            layout.preview_layout(self.kodi, self.index, body)
        os.unlink(os.path.join(self.root, 'skin.bingie-kids-1.DATA.xml'))
        body['expected_revision'] = layout.preview_layout(self.kodi, self.index, body)['revision']
        old = self.read('skin.bingie-mainmenu.DATA.xml')
        self.put('skin.bingie-31227-1.DATA.xml', b'<shortcuts><!-- external --></shortcuts>')
        with self.assertRaisesRegex(ValueError, 'changed since preview'):
            layout.apply_layout(self.kodi, self.index, body, True)
        self.assertEqual(self.read('skin.bingie-mainmenu.DATA.xml'), old)

    def test_repurpose_failure_after_linked_delete_rolls_back_every_file(self):
        body = self.repurpose_fixture()
        body['expected_revision'] = layout.preview_layout(self.kodi, self.index, body)['revision']
        before = {name: self.read(name) for name in os.listdir(self.root) if name.startswith('skin.bingie-')}
        atomic = layout._atomic
        properties_path = os.path.join(os.path.realpath(self.root), 'skin.bingie.properties')
        def failing(path, raw):
            if path == properties_path:
                raise OSError('failed after migration')
            return atomic(path, raw)
        with patch.object(layout, '_atomic', side_effect=failing):
            with self.assertRaisesRegex(OSError, 'after migration'):
                layout.apply_layout(self.kodi, self.index, body, True)
        self.assertEqual({name: self.read(name) for name in os.listdir(self.root) if name.startswith('skin.bingie-')}, before)

    def test_general_source_change_queries_only_changed_route(self):
        body = self.general_fixture()
        body['rows'][0]['path'] = 'plugin://plugin.video.test/?info=family'
        with patch.object(self.kodi, 'jsonrpc', wraps=self.kodi.jsonrpc) as rpc:
            layout.apply_layout(self.kodi, self.index, body, True)
            self.assertEqual(rpc.call_count, 1)
            self.assertEqual(rpc.call_args.args[1]['media'], 'video')

    def test_general_rejects_unknown_row_ids_actions_and_section_aliases(self):
        body = self.general_fixture()
        for mutation in ({'id': 'invented'}, {'action': 'RunScript(evil)'}, {'path': 'plugin://script.trakt/'}):
            altered = dict(body, rows=[dict(body['rows'][0], **mutation)])
            with self.assertRaises(ValueError):
                layout.preview_layout(self.kodi, self.index, altered)
        with self.assertRaises(ValueError):
            layout.preview_layout(self.kodi, self.index, dict(body, section_id='hub:../escape'))

    def test_general_detects_native_edit_during_staged_write_and_rolls_back(self):
        body = self.general_fixture()
        body['rows'][0]['label'] = 'Fresh'
        original_hub = self.read('skin.bingie-moviehub.DATA.xml')
        atomic = layout._atomic
        hub_path = os.path.join(os.path.realpath(self.root), 'skin.bingie-moviehub.DATA.xml')

        def concurrent(path, raw):
            atomic(path, raw)
            if path == hub_path and b'Fresh' in raw:
                self.put('skin.bingie.properties', b"[['other','keep','sort','new']]" )

        with patch.object(layout, '_atomic', side_effect=concurrent):
            with self.assertRaisesRegex(ValueError, 'changed during staging'):
                layout.apply_layout(self.kodi, self.index, body, True)
        self.assertEqual(self.read('skin.bingie-moviehub.DATA.xml'), original_hub)
        self.assertIn(b"'new'", self.read('skin.bingie.properties'))

    def test_malformed_properties_inspection_is_read_only(self):
        self.general_fixture()
        self.put('skin.bingie.properties', b'not a properties literal')
        state = layout.inspect_layout(self.kodi, self.index)
        self.assertFalse(state['can_apply'])
        self.assertTrue(state['sections'])

    def test_rebuild_verifies_schema_and_only_reports_dispatch(self):
        native, gui = Mock(), Mock()
        with patch('kodi_api.xbmc', native), patch('kodi_api.xbmcgui', gui):
            result = layout.request_rebuild(self.kodi, self.index)
        self.assertEqual(result, {'started': True})
        gui.Window.assert_called_once_with(10000)
        gui.Window.return_value.setProperty.assert_called_once_with('skinshortcuts-reloadmainmenu', 'True')
        native.executebuiltin.assert_called_once_with(layout.REBUILD)

    def test_rebuild_passes_all_parameters_in_the_single_argv_query(self):
        from urllib.parse import parse_qsl
        # Kodi separates RunScript arguments at commas; Skin Shortcuts 2.0.3
        # parses only sys.argv[1] with parse_qsl. Separate parameter arguments
        # silently default mainmenuID/levels/group and omit widget templates.
        builtin_arguments = layout.REBUILD[len('RunScript('):-1].split(',')
        self.assertEqual(builtin_arguments[0], 'script.skinshortcuts')
        self.assertEqual(len(builtin_arguments), 2)
        parsed = dict(parse_qsl(builtin_arguments[1]))
        self.assertEqual(parsed['type'], 'buildxml')
        self.assertEqual(parsed['mainmenuID'], '900')
        self.assertEqual(parsed['levels'], '1')
        self.assertEqual(parsed['group'].split('|'), [
            'mainmenu', 'powermenu', 'searchmenu', 'tmdbsearchmenu', 'moviehub',
            'tvshowhub', 'newhub', 'musichub', 'customhub', 'somethinghub', 'mylisthub'])

    def test_rebuild_rejects_unknown_schema_before_native_mutation(self):
        native, gui = Mock(), Mock()
        with patch('kodi_api.xbmc', native), patch('kodi_api.xbmcgui', gui), patch.object(layout, '_verify_sources', side_effect=ValueError('Unverified schema')):
            with self.assertRaisesRegex(ValueError, 'Unverified schema'):
                layout.request_rebuild(self.kodi, self.index)
        native.executebuiltin.assert_not_called()
        gui.Window.assert_not_called()

    def test_rebuild_requires_native_kodi_runtime(self):
        with patch('kodi_api.xbmc', None), patch('kodi_api.xbmcgui', None):
            with self.assertRaisesRegex(ValueError, 'inside the Kodi Manager service'):
                layout.request_rebuild(self.kodi, self.index)


if __name__ == "__main__":
    unittest.main()
