from .base import BaseAdapter

try:
    from ..kodi_api import safe_listdir
except (ImportError, ValueError):  # Python 3.8 raises ValueError past the top-level package
    from kodi_api import safe_listdir


class FenLightAdapter(BaseAdapter):
    addon_ids = ["plugin.video.fenlight"]
    display_name = "Fen Light"

    def get_warnings(self, addon_info):
        return ["External scraper settings are displayed by schema only. Provider sources are not fetched or configured."]

    def extra_details(self, addon_info):
        cocos = self.index.get("script.module.cocoscrapers") if self.index else None
        data = addon_info.get("addon_data_path") or ""
        db = (data.rstrip("/\\") + "/databases") if data else ""
        listing = safe_listdir(db) if db else {"files": []}
        return {
            "cocoscrapers": {"installed": bool(cocos), "enabled": bool(cocos and cocos.get("enabled")), "version": cocos.get("version") if cocos else ""},
            "databases_path": db,
            "database_files": sorted([f for f in listing.get("files", []) if f.endswith(".db")]),
        }
