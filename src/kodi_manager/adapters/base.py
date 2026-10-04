class BaseAdapter:
    addon_ids = []
    display_name = "Generic"
    supports_generic_settings = True
    safe_edit_supported = True

    def __init__(self, kodi=None, index=None):
        self.kodi = kodi
        self.index = index

    @property
    def name(self):
        return self.__class__.__name__

    def get_warnings(self, addon_info):
        return []

    def extra_details(self, addon_info):
        return {}

    def normalize_setting(self, setting):
        return setting

    def is_edit_allowed(self, setting):
        return bool(setting.get("editable"))

    def before_write(self, addon_id, changes):
        return []

    def after_write(self, addon_id, changes):
        return ["Kodi restart may be required."]
