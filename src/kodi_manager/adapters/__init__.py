from .generic import GenericAdapter
from .bingie_skin import BingieSkinAdapter
from .tmdbhelper import TMDbHelperAdapter
from .fenlight import FenLightAdapter
from .cocoscrapers import CocoScrapersAdapter
from .trakt import TraktAdapter

ADAPTER_CLASSES = [BingieSkinAdapter, TMDbHelperAdapter, FenLightAdapter, CocoScrapersAdapter, TraktAdapter]


def adapter_for(addon_info, kodi=None, index=None):
    aid = addon_info.get("addon_id") or addon_info.get("id") or ""
    name = (addon_info.get("name") or "").lower()
    for cls in ADAPTER_CLASSES:
        if aid in cls.addon_ids:
            return cls(kodi, index)
    if "bingie" in aid.lower() or "bingie" in name:
        if aid.startswith("plugin.video.") and ("tmdb" in aid.lower() or "themoviedb" in aid.lower()):
            return TMDbHelperAdapter(kodi, index)
        return BingieSkinAdapter(kodi, index)
    if ("tmdb" in name and "helper" in name) or ("tmdb" in aid.lower() and "helper" in aid.lower()) or "themoviedb" in aid.lower():
        return TMDbHelperAdapter(kodi, index)
    if "fen light" in name or "fenlight" in aid.lower() or aid == "plugin.video.fen":
        return FenLightAdapter(kodi, index)
    if "cocoscrapers" in name or "cocoscrapers" in aid.lower():
        return CocoScrapersAdapter(kodi, index)
    if "trakt" in name or aid == "script.trakt":
        return TraktAdapter(kodi, index)
    return GenericAdapter(kodi, index)
