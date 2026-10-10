"""Memory pressure for the Health page (Linux and Android; elsewhere "unknown").

The service runs inside Kodi, so /proc/self is Kodi itself. When the device
runs out of memory and swap, Android slows everything down, network included,
and add-ons start timing out.
"""


def _kb_fields(path, wanted):
    values = {}
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                key, _, rest = line.partition(":")
                if key in wanted:
                    values[key] = int(rest.split()[0])
    except (OSError, ValueError, IndexError):
        return {}
    return values


def memory_status(meminfo="/proc/meminfo", self_status="/proc/self/status"):
    info = _kb_fields(meminfo, ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree"))
    kodi = _kb_fields(self_status, ("VmRSS",))
    if not info.get("MemTotal") or "MemAvailable" not in info:
        return {"status": "unknown", "detail": "Memory figures are not available on this system"}
    mb = lambda kb: int(round(kb / 1024.0))  # noqa: E731
    total, available = info["MemTotal"], info.get("MemAvailable", 0)
    swap_total, swap_free = info.get("SwapTotal", 0), info.get("SwapFree", 0)
    swap_used_pct = int(round(100.0 * (swap_total - swap_free) / swap_total)) if swap_total else 0
    problems = []
    if available < min(300 * 1024, total * 0.10):
        problems.append("only %s MB free" % mb(available))
    # Android keeps cold pages in compressed swap even after RAM is available.
    # Swap occupancy alone is not evidence of current memory pressure.
    if problems and swap_total and swap_used_pct >= 90:
        problems.append("swap %s%% full" % swap_used_pct)
    status = "warning" if problems else "ok"
    detail = "Kodi uses %s MB · %s MB of %s MB free%s" % (
        mb(kodi.get("VmRSS", 0)), mb(available), mb(total),
        " · swap %s%% used" % swap_used_pct if swap_total else "")
    if problems:
        detail += ". Low memory (%s): restart Kodi or the device if add-ons start timing out." % ", ".join(problems)
    return {"status": status, "detail": detail, "kodi_mb": mb(kodi.get("VmRSS", 0)),
            "available_mb": mb(available), "total_mb": mb(total), "swap_used_pct": swap_used_pct}
