"""Local certification/genre filters for a Kodi directory listing."""
import re

MAX_RATING_OPTIONS = ("U", "PG", "12A", "15")
_AGES = {"U": 0, "G": 0, "PG": 8, "12": 12, "12A": 12, "PG13": 12, "15": 15, "18": 18,
         "TVY": 0, "TVY7": 7, "TVY7FV": 7, "TVG": 0, "TVPG": 8, "TV14": 14, "TVMA": 18, "R": 17, "NC17": 18}
_RATING_RE = re.compile(r"(?<![A-Z0-9])(?:TV[- ]?(?:Y7(?:[- ]?FV)?|Y|G|PG|14|MA)|PG[- ]?13|NC[- ]?17|12A|12|15|18|PG|U|G|R)(?![A-Z0-9])", re.I)
_UNRATED_RE = re.compile(r"\b(?:UNRATED|UNKNOWN|NOT\s+RATED|NR|N/A|NONE|TBC|NOT\s+YET\s+RATED)\b", re.I)
_FAMILY_GENRES = {"family", "kids", "children", "children's", "childrens", "kids & family", "children & family"}


def _metadata(item, key):
    info = item.get("info") or {}
    if not isinstance(info, dict):
        info = {}
    for obj in (item, info, info.get("video", {}), item.get("metadata", {})):
        if isinstance(obj, dict) and obj.get(key) not in (None, "", []):
            return obj[key]
    return None


def certification_age(item):
    info = item.get("info") if isinstance(item.get("info"), dict) else {}
    objects = (item, info, info.get("video", {}), item.get("metadata", {}))
    values = [obj[key] for obj in objects if isinstance(obj, dict)
              for key in ("mpaa", "certification", "content_rating") if obj.get(key)]
    ages = []
    for value in values:
        if not isinstance(value, str):
            return None
        if not value.strip():
            continue
        if _UNRATED_RE.search(value):
            return None
        # Unknown certifications in a multi-country string cannot be discarded
        # merely because another country's certification is recognized.
        for part in re.split(r"\s*[/|;+]\s*", value):
            remainder = _RATING_RE.sub("", part)
            remainder = re.sub(r"\b(?:RATED|UK|GB|US|USA|UNITED KINGDOM|UNITED STATES|BBFC|MPAA)\b", "", remainder, flags=re.I)
            if re.search(r"[A-Za-z0-9]", remainder):
                return None
        matches = _RATING_RE.findall(value.upper())
        if not matches:
            return None
        ages.extend(_AGES[re.sub(r"[- ]", "", match)] for match in matches)
    return max(ages) if ages else None


def _family_genre(item):
    value = _metadata(item, "genre") or _metadata(item, "genres") or []
    if isinstance(value, str):
        value = re.split(r"\s*[,/|;]\s*", value)
    if not isinstance(value, (tuple, list)):
        return False
    return any(isinstance(genre, str) and genre.strip().casefold() in _FAMILY_GENRES for genre in value)


def filter_items(files, max_rating="12A", family_only=True):
    """Preserve original item dictionaries. Review scores are never age ratings."""
    if max_rating not in MAX_RATING_OPTIONS:
        raise ValueError("max_rating must be U, PG, 12A, or 15")
    if not isinstance(family_only, bool):
        raise ValueError("family_only must be boolean")
    if not isinstance(files, (tuple, list)):
        raise ValueError("Directory files must be a list")
    out = []
    excluded = {"unknown_rating": 0, "above_rating": 0, "non_family_genre": 0, "invalid_item": 0, "pagination": 0}
    for item in files:
        if not isinstance(item, dict):
            excluded["invalid_item"] += 1
            continue
        label = re.sub(r"\[/?(?:COLOR[^\]]*|B|I)\]", "", str(item.get("label") or ""), flags=re.I).strip().casefold()
        if label in ("next page", "previous page", "load more", "next page >>", "next >>", "more results"):
            excluded["pagination"] += 1
            continue
        age = certification_age(item)
        if age is None:
            excluded["unknown_rating"] += 1
        elif age > _AGES[max_rating]:
            excluded["above_rating"] += 1
        elif family_only and not _family_genre(item):
            excluded["non_family_genre"] += 1
        else:
            out.append(item)
    return {"files": out, "excluded_counts": excluded, "input_count": len(files), "included_count": len(out),
            "max_rating": max_rating, "family_only": family_only}
