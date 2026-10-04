from .base import BaseAdapter


class TraktAdapter(BaseAdapter):
    addon_ids = ["script.trakt"]
    display_name = "Trakt"

    def get_warnings(self, addon_info):
        return ["Auth state is masked. This tool does not reauthorize Trakt or manipulate tokens."]
