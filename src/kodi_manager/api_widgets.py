"""API handlers for home rows: the widget cache, cached rows, browsing, the layout editor and tested fixes.
"""
try:
    from .http_base import RequestHandler
    from .dashboard_data import WIDGET_CACHE_DIR, with_row_titles
    from .fix_protection import protection_for_kodi
    from .kodi_api import translate
    from .widget_catalog import list_sources, browse_directory, suggest_kids_rows
    from .widget_filters import filter_items
    from .widget_preview import row_preview
    from .skin_layout import inspect_layout, preview_layout, apply_layout, request_rebuild
    from .widget_cache import WidgetCache, cache_url
    from .widget_rows import RowStore
except ImportError:
    from http_base import RequestHandler
    from dashboard_data import WIDGET_CACHE_DIR, with_row_titles
    from fix_protection import protection_for_kodi
    from kodi_api import translate
    from widget_catalog import list_sources, browse_directory, suggest_kids_rows
    from widget_filters import filter_items
    from widget_preview import row_preview
    from skin_layout import inspect_layout, preview_layout, apply_layout, request_rebuild
    from widget_cache import WidgetCache, cache_url
    from widget_rows import RowStore


def _lock_layout(layout):
    """Read-only presentation of a layout while Write Mode is off."""
    layout["can_apply"] = False
    layout["new_section_available"] = False
    for section in layout.get("sections", []):
        section["editable"] = False
    layout["reasons"] = list(layout.get("reasons", [])) + ["Write Mode is disabled. Enable it in Kodi Manager service settings to apply this layout."]
    return layout


class WidgetRoutes(RequestHandler):
    """Widget cache, fixes, widget sources and home layout (``/api/widget-cache``, ``/api/widgets``, ``/api/fixes``)."""

    def _rows(self):
        return RowStore(translate(WIDGET_CACHE_DIR))

    # --- widget cache --------------------------------------------------------

    def api_widget_cache_url(self):
        pages = self.query("pages")
        return {"url": cache_url(self.query("source"), pages=int(pages) if pages.isdigit() else None,
                                 hide_watched=self.query("hide_watched") == "true")}

    def api_widget_rows_list(self):
        return self._rows().listing()

    def api_widget_rows_add(self):
        body = self.body()
        pages = body.get("pages")
        return self._rows().add(body.get("label", ""), body.get("source", ""),
                                pages=int(pages) if str(pages or "").isdigit() else None,
                                hide_watched=bool(body.get("hide_watched")))

    def api_widget_rows_remove(self):
        self._rows().remove(str(self.body().get("id", "")))
        return {"removed": True}

    def api_widget_cache_status(self):
        status = WidgetCache(translate(WIDGET_CACHE_DIR)).status()
        try:
            status["entries"] = with_row_titles(self.state.kodi, self.state.index, status.get("entries") or [])
        except Exception as exc:  # titles are a nicety: never fail the listing over them
            self.state.log("Row titles unavailable: %s" % type(exc).__name__)
        return status

    def api_widget_cache_refresh(self):
        return {"queued": WidgetCache(translate(WIDGET_CACHE_DIR)).queue_stale(everything=True)}

    # --- fixes ---------------------------------------------------------------

    def api_fixes_status(self):
        return protection_for_kodi().status()

    def api_fixes_repair(self):
        self._require_idle("Stop playback before restoring fixes")
        return protection_for_kodi().repair()

    # --- widgets and layout --------------------------------------------------

    def api_widget_sources(self):
        self.state.index.refresh()
        return list_sources(self.state.kodi, self.state.index)

    def api_widget_layout(self):
        self.state.index.refresh()
        layout = inspect_layout(self.state.kodi, self.state.index)
        return layout if self.state.config.get("write_enabled") else _lock_layout(layout)

    def api_widget_browse(self):
        body = self.body()
        if not isinstance(body.get("family_preview", False), bool):
            raise ValueError("family_preview must be boolean")
        self.state.index.refresh()
        result = browse_directory(self.state.kodi, self.state.index, body.get("path", ""), body.get("start", 0), body.get("limit", 48), refresh=body.get("refresh", False))
        if body.get("family_preview"):
            result["family_preview"] = filter_items([dict(item, file=item["path"]) for item in result["items"]], body.get("max_rating", "12A"), True)
        return result

    def api_widget_suggestions(self):
        self.body()
        self.state.index.refresh()
        return suggest_kids_rows(self.state.kodi, self.state.index)

    def api_widget_row_preview(self):
        body = self.body()
        self.state.index.refresh()
        return row_preview(self.state.kodi, self.state.index, body)

    def api_widget_layout_preview(self):
        body = self.body()
        self.state.index.refresh()
        layout = preview_layout(self.state.kodi, self.state.index, body)
        return layout if self.state.config.get("write_enabled") else _lock_layout(layout)

    def api_widget_layout_apply(self):
        body = self.body()
        self.state.index.refresh()
        return apply_layout(self.state.kodi, self.state.index, body, True)

    def api_widget_layout_rebuild(self):
        self.body()
        self.state.index.refresh()
        # Rebuilding reloads the skin, which interrupts whoever is watching.
        self._require_idle("Stop playback before rebuilding the TV menu")
        return request_rebuild(self.state.kodi, self.state.index)
