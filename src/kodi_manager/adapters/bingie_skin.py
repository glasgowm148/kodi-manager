from .base import BaseAdapter


class BingieSkinAdapter(BaseAdapter):
    addon_ids = ["skin.titan.bingie.mod", "skin.titan.bingie"]
    display_name = "Bingie/Titan Bingie Skin"
    safe_edit_supported = False

    def get_warnings(self, addon_info):
        return [
            "Bingie widget layouts and shortcuts may be stored by skin helper/skin shortcuts add-ons, not only the skin add-on itself.",
            "Full visual widget editing is outside MVP.",
            "Skin settings are read-only in MVP.",
        ]

    def is_edit_allowed(self, setting):
        return False
