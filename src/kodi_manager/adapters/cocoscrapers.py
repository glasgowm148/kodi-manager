from .base import BaseAdapter


class CocoScrapersAdapter(BaseAdapter):
    addon_ids = ["script.module.cocoscrapers"]
    display_name = "CocoScrapers"

    def get_warnings(self, addon_info):
        return ["Changing provider settings may affect Fen Light behavior. No providers or sources are fetched by this tool."]
