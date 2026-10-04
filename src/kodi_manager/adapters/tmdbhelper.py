import os
from .base import BaseAdapter


class TMDbHelperAdapter(BaseAdapter):
    addon_ids = ["plugin.video.themoviedb.helper"]
    display_name = "TMDb Helper"

    def get_warnings(self, addon_info):
        return ["TMDb Helper players and library integration can involve files outside normal settings. MVP shows these read-only unless explicitly supported."]

    def extra_details(self, addon_info):
        data = addon_info.get("addon_data_path")
        players = os.path.join(data, "players") if data else ""
        library = os.path.join(data, "library") if data else ""
        return {
            "players_path": players,
            "player_files": sorted([f for f in os.listdir(players) if f.endswith(".json")]) if os.path.isdir(players) else [],
            "library_path": library,
            "library_exists": os.path.isdir(library),
        }
