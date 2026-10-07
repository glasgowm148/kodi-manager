from kodi_manager.memstat import memory_status


def _write(tmp_path, meminfo, rss_kb=650000):
    m = tmp_path / "meminfo"
    m.write_text(meminfo)
    s = tmp_path / "status"
    s.write_text("Name:\tkodi\nVmRSS:\t%d kB\n" % rss_kb)
    return str(m), str(s)


def test_full_swap_and_little_free_memory_warns(tmp_path):
    # The Shield state that made POV's TorBox lookups time out.
    m, s = _write(tmp_path, "MemTotal: 3023620 kB\nMemAvailable: 98000 kB\nSwapTotal: 524284 kB\nSwapFree: 200 kB\n")
    result = memory_status(m, s)
    assert result["status"] == "warning"
    assert "swap 100% full" in result["detail"] and "Kodi uses 635 MB" in result["detail"]


def test_healthy_memory_is_ok(tmp_path):
    m, s = _write(tmp_path, "MemTotal: 3023620 kB\nMemAvailable: 1390428 kB\nSwapTotal: 524284 kB\nSwapFree: 400000 kB\n", 400000)
    assert memory_status(m, s)["status"] == "ok"


def test_missing_proc_is_unknown(tmp_path):
    assert memory_status(str(tmp_path / "nope"), str(tmp_path / "nope2"))["status"] == "unknown"
