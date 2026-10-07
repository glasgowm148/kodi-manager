"""ListItem metadata that works on Kodi 19 (setInfo) and Kodi 20+ (InfoTagVideo setters).

Kodi 19 has ``ListItem.getVideoInfoTag()`` but its tag only has getters, so
every setter must be looked up with ``getattr`` and anything the tag cannot
take goes to ``ListItem.setInfo``. Kodi 20+ warns about ``setInfo``, so it is
only called for values that no setter accepted.

``info`` uses ``ListItem.setInfo`` labels (title, tvshowtitle, duration, ...).
Only stdlib imports: this runs in every widget invocation.
"""

SIMPLE_SETTERS = {
    "title": "setTitle", "year": "setYear", "mpaa": "setMpaa", "plot": "setPlot",
    "tagline": "setTagLine", "originaltitle": "setOriginalTitle", "imdbnumber": "setIMDBNumber",
    "premiered": "setPremiered", "aired": "setFirstAired", "trailer": "setTrailer",
    "lastplayed": "setLastPlayed", "dateadded": "setDateAdded", "playcount": "setPlaycount",
    "tvshowtitle": "setTvShowTitle", "duration": "setDuration", "season": "setSeason",
    "episode": "setEpisode", "mediatype": "setMediaType",
}
LIST_SETTERS = {
    "genre": "setGenres", "director": "setDirectors", "writer": "setWriters",
    "studio": "setStudios", "country": "setCountries", "tag": "setTags",
}


def video_tag(li):
    getter = getattr(li, "getVideoInfoTag", None)
    if getter is None:
        return None
    try:
        return getter()
    except Exception:
        return None


def _setter(tag, name):
    return getattr(tag, name, None) if tag is not None else None


def set_video_info(li, info, resume=None, unique_ids=None, default_id="", rating=None, votes=0,
                   cast=None, actor=None):
    """Apply metadata to ``li`` with whatever API this Kodi version offers.

    ``rating``/``votes``: numeric rating; ``unique_ids``: {name: id};
    ``resume``: {"position", "total"}; ``cast``: [{"name", "role", "order", "thumbnail"}];
    ``actor``: ``xbmc.Actor`` when available (Kodi 20+).
    """
    tag = video_tag(li)
    fallback = {}
    for key, value in (info or {}).items():
        name = SIMPLE_SETTERS.get(key) or LIST_SETTERS.get(key)
        setter = _setter(tag, name) if name else None
        if setter is None:
            fallback[key] = value
            continue
        if key in LIST_SETTERS:
            value = [str(v) for v in (value if isinstance(value, (list, tuple)) else [value]) if v]
        try:
            setter(value)
        except (TypeError, ValueError):
            pass
    if rating is not None:
        setter = _setter(tag, "setRating")
        try:
            if setter is not None:
                setter(float(rating), int(votes or 0), "", True)
            else:
                fallback["rating"] = float(rating)
                if votes:
                    fallback["votes"] = str(votes)
        except (TypeError, ValueError):
            pass
    if fallback and hasattr(li, "setInfo"):
        li.setInfo("video", fallback)
    if unique_ids:
        ids = {str(k): str(v) for k, v in unique_ids.items() if k and v}
        default = default_id if default_id in ids else ("tmdb" if "tmdb" in ids else next(iter(ids), ""))
        setter = _setter(tag, "setUniqueIDs") or getattr(li, "setUniqueIDs", None)
        if ids and setter is not None:
            try:
                setter(ids, default)
            except (TypeError, ValueError):
                pass
    resume = resume or {}
    if resume.get("position"):
        setter = _setter(tag, "setResumePoint")
        try:
            if setter is not None:
                setter(float(resume["position"]), float(resume.get("total") or 0))
            elif hasattr(li, "setProperty"):
                li.setProperty("ResumeTime", str(resume["position"]))
                li.setProperty("TotalTime", str(resume.get("total") or 0))
        except (TypeError, ValueError):
            pass
    if cast:
        setter = _setter(tag, "setCast")
        try:
            if setter is not None and actor is not None:
                setter([actor(c.get("name", ""), c.get("role", ""), int(c.get("order", i)), c.get("thumbnail", ""))
                        for i, c in enumerate(cast)])
            elif hasattr(li, "setCast"):
                li.setCast([{"name": c.get("name", ""), "role": c.get("role", ""),
                             "order": int(c.get("order", i)), "thumbnail": c.get("thumbnail", "")}
                            for i, c in enumerate(cast)])
        except (TypeError, ValueError):
            pass
