"""API handlers for add-ons and their settings: listing and search, one add-on's settings,
backups, checkpoints, protected settings and restores.
"""
try:
    from .http_base import ApiError, RequestHandler
    from .adapters import adapter_for
    from .backup import BackupAborted, create_backup, create_stack_backup, list_backups, restore_backup, restore_stack_backup
    from .settings_schema import parse_schema, flatten_settings, parse_user_settings
    from .dashboard_data import backup_timeline, make_baseline, settings_for_addon, stack_backup_addons
    from .pipeline import write_settings
    from .validation import coerce_setting
    from . import fenlight_db
    from .write_policy import RequestRefused, check_writable, read_only_reason
except ImportError:
    from http_base import ApiError, RequestHandler
    from adapters import adapter_for
    from backup import BackupAborted, create_backup, create_stack_backup, list_backups, restore_backup, restore_stack_backup
    from settings_schema import parse_schema, flatten_settings, parse_user_settings
    from dashboard_data import backup_timeline, make_baseline, settings_for_addon, stack_backup_addons
    from pipeline import write_settings
    from validation import coerce_setting
    import fenlight_db
    from write_policy import RequestRefused, check_writable, read_only_reason


class AddonRoutes(RequestHandler):
    """Add-ons, settings search, one add-on, install, checkpoints, protected settings and restores."""

    def api_addons(self):
        self.state.index.refresh()
        return self.state.index.list()

    def api_search_config(self):
        self.state.index.refresh()
        q = self.query("q").lower().strip()
        if not q:
            return {"query": q, "results": []}
        results = []
        for addon in self.state.index.list():
            parsed = settings_for_addon(addon)
            for group in parsed.get("groups", []):
                for setting in group.get("settings", []):
                    hay = " ".join(str(x or "") for x in [addon.get("addon_id"), addon.get("name"), group.get("label"), setting.get("id"), setting.get("label"), setting.get("value")]).lower()
                    if q in hay:
                        results.append({
                            "addon_id": addon.get("addon_id"),
                            "addon_name": addon.get("name"),
                            "version": addon.get("version", ""),
                            "group": group.get("label"),
                            "id": setting.get("id"),
                            "label": setting.get("label"),
                            "value": setting.get("value"),
                            "type": setting.get("type"),
                            "description": setting.get("description"),
                            "editable": setting.get("editable"),
                            "masked": setting.get("masked"),
                            "warning": setting.get("warning"),
                        })
                    if len(results) >= 500:
                        return {"query": q, "count": len(results), "results": results}
        return {"query": q, "count": len(results), "results": results}

    # --- install, backups, restores --------------------------------------------

    def api_addons_install(self):
        self.body()
        self._require_idle("Stop playback before opening Install from zip on the TV")
        return self.state.kodi.open_install_from_zip()

    def api_stack_backup(self):
        # Copying addon_data competes with playback for storage, like the nightly checkpoint:
        # refuse while something plays and stop (discarding it) if playback starts.
        self._require_idle("Stop playback before taking a checkpoint", status=409)
        should_stop = self._backup_should_stop(playback=True)
        try:
            addons = stack_backup_addons(self.state.kodi, self.state.index)
            version = self.state.kodi.get_kodi_version()
            self._check_context()
            return create_stack_backup(addons, version, should_stop=should_stop)
        except BackupAborted as exc:
            raise self._backup_aborted(exc, should_stop, "checkpoint") from None

    def _backup_should_stop(self, playback=False):
        """A should_stop callback for snapshots taken by a request.

        Returns "stopping" once the service has retired (checked first, so no Kodi call is
        made after that), then, with ``playback``, "playback" once a player is active.
        The last reason is kept in ``should_stop.reason`` for _backup_aborted.
        """
        playing = self._playback_started() if playback else None

        state = self.state

        class ShouldStop:
            reason = None

            def __call__(self):
                if getattr(state, "retired", False):
                    self.reason = "stopping"
                elif playing is not None and playing():
                    self.reason = "playback"
                else:
                    return False
                return self.reason

        return ShouldStop()

    @staticmethod
    def _backup_aborted(exc, should_stop, what):
        """The API error for a snapshot that was stopped and discarded (nothing changed)."""
        reason = getattr(exc, "reason", "stopped")
        if reason == "stopped":
            reason = getattr(should_stop, "reason", None) or reason
        if reason == "playback":
            return ApiError(409, "playback_active", "Playback started, so the %s was stopped and discarded" % what)
        if reason == "stopping":
            return ApiError(409, "server_retired", "Manager service stopped, so the %s was stopped and discarded; "
                                                   "reconnect and inspect before retrying" % what)
        # stale_revision is a refusal: the operation record shows nothing was changed.
        if reason == "busy_database":
            return ApiError(409, "stale_revision", "An add-on was writing to its database, so the %s was discarded "
                                                   "and nothing changed. Try again in a minute." % what)
        return ApiError(409, "stale_revision", "The %s was stopped and discarded; nothing changed. Try again." % what)

    def api_baseline(self):
        rows = make_baseline(self.state.kodi).check()
        return {"items": rows, "count": len(rows), "drifted": len([r for r in rows if not r["ok"] and not r["missing"]])}

    def api_baseline_apply(self):
        keys = self.body().get("keys") or None
        if keys is not None and (not isinstance(keys, list) or not all(isinstance(k, str) for k in keys)):
            raise ValueError("keys must be a list of strings")
        # Re-applying can restart add-ons or reload the skin: never during playback.
        self._require_idle("Stop playback before re-applying protected settings", status=409)
        return make_baseline(self.state.kodi).apply(keys, check=self._baseline_writable)

    def api_baseline_capture(self):
        items = self.body().get("items")
        if not isinstance(items, list) or not items:
            raise ValueError("items must be a non-empty list")
        return make_baseline(self.state.kodi).capture(items, check=self._baseline_writable)

    def _baseline_writable(self, item):
        """Protected add-on items obey the same write policy as the settings editor."""
        if item.get("kind") in ("addon_setting", "addon_xml"):
            check_writable(item["addon"], self.state.index.get(item["addon"]), self.state.config)

    def api_baseline_remove(self):
        keys = self.body().get("keys")
        if not isinstance(keys, list):
            raise ValueError("keys must be a list")
        return make_baseline(self.state.kodi).remove(keys)

    def api_stack_backups(self):
        return {"backups": list_backups(stack=True)}

    def api_backups_timeline(self):
        return backup_timeline()

    def api_stack_restore(self):
        backup_id = self.body().get("backup_id", "")
        self._require_idle_unless_forced("Stop playback before restoring a backup")
        should_stop = self._backup_should_stop()
        try:
            return restore_stack_backup(self.state.index, backup_id, should_stop=should_stop)
        except BackupAborted as exc:
            # Raised while taking the undo snapshots, before any live folder was touched.
            raise self._backup_aborted(exc, should_stop, "restore's undo snapshot") from None

    # --- one add-on ----------------------------------------------------------------

    def api_addon_details(self, aid):
        addon = self._addon(aid)
        adapter = adapter_for(addon, self.state.kodi, self.state.index.addons)
        details = dict(addon)
        details["warnings"] = adapter.get_warnings(addon)
        details["related"] = adapter.extra_details(addon)
        return details

    def api_addon_settings(self, aid):
        addon = self._addon(aid)
        adapter = adapter_for(addon, self.state.kodi, self.state.index.addons)
        parsed = settings_for_addon(addon)
        reason = read_only_reason(aid, addon, self.state.config)
        parsed.update({"addon_id": aid, "name": addon.get("name"), "adapter": adapter.name,
                       "warnings": parsed.get("warnings", []) + adapter.get_warnings(addon),
                       "editable": reason is None, "read_only_reason": reason})
        parsed["addon_info"] = {key: addon.get(key) for key in
                                ("purpose", "role_label", "has_service", "required_by", "cleanup", "description")}
        return parsed

    def api_addon_settings_patch(self, aid):
        addon = self._addon(aid)
        check_writable(aid, addon, self.state.config)
        adapter = adapter_for(addon, self.state.kodi, self.state.index.addons)
        changes = self.body().get("changes", [])
        if not isinstance(changes, list):
            raise ValueError("changes must be a list")
        settings = flatten_settings(parse_schema(addon.get("settings_schema_path"), addon.get("path"), addon.get("user_settings_path"), True))
        clean, db_pairs = [], []
        try:
            for ch in changes:
                if not isinstance(ch, dict):
                    raise ValueError("Each change must be an object")
                sid = ch.get("id")
                if not isinstance(sid, str):
                    # A list or object id would fail the lookups below with a TypeError.
                    raise RequestRefused("Each change needs a setting id")
                if aid == fenlight_db.FENLIGHT_ID and ch.get("source") == "settings.db":
                    db_pairs.append((sid, ch.get("value")))
                    continue
                if ch.get("source") == "raw":
                    raw = parse_user_settings(addon.get("user_settings_path"))
                    if sid not in raw:
                        raise RequestRefused("Unknown raw setting: %s" % sid)
                    if ch.get("value") is None or isinstance(ch.get("value"), (dict, list)):
                        raise ValueError("Expected a single value: %s" % sid)
                    clean.append({"id": sid, "value": str(ch.get("value")), "source": "raw", "previous": raw[sid]})
                    continue
                if sid not in settings:
                    raise RequestRefused("Unknown setting: %s" % sid)
                setting = settings[sid]
                if not setting.get("editable"):
                    raise RequestRefused("Setting not editable: %s" % sid)
                clean.append({"id": sid, "value": coerce_setting(sid, setting, ch.get("value")), "previous": setting.get("value") or ""})
            # The whole batch is validated (including settings.db types) before anything is written.
            db_clean = fenlight_db.validate_changes(addon, db_pairs) if db_pairs else []
        except RequestRefused:
            raise
        except ValueError as exc:
            # Raised while validating, before anything is written: a refusal, not an unknown outcome.
            raise RequestRefused(str(exc), setting_id=getattr(exc, "setting_id", None)) from exc
        try:
            backup = create_backup(addon, self.state.kodi.get_kodi_version(), adapter.name)
        except BackupAborted as exc:
            raise self._backup_aborted(exc, None, "backup before saving") from None
        # Rolls back the settings already written if any write in the batch fails.
        # Previous values stay out of the response and the adapter's after_write hook.
        writes = [(aid, ch["id"], ch["value"], ch.pop("previous")) for ch in clean]
        self._check_context()
        write_settings(self.state.kodi, writes, [(addon, db_clean)] if db_clean else [])
        clean += [{"id": sid, "value": value, "source": "settings.db"} for sid, value in db_clean]
        return {"changed_count": len(clean), "backup_id": backup["backup_id"], "warnings": adapter.after_write(aid, clean)}

    def api_addon_open_settings(self, aid):
        self._addon(aid)
        # A settings dialog opens over whatever is on screen, including a film.
        self._require_idle("Stop playback before opening settings on the TV")
        return {"opened": self.state.kodi.open_addon_settings(aid)}

    def api_addon_backup(self, aid):
        addon = self._addon(aid)
        adapter = adapter_for(addon, self.state.kodi, self.state.index.addons)
        version = self.state.kodi.get_kodi_version()
        self._check_context()
        should_stop = self._backup_should_stop()
        try:
            return create_backup(addon, version, adapter.name, should_stop=should_stop)
        except BackupAborted as exc:
            raise self._backup_aborted(exc, should_stop, "backup") from None

    def api_addon_backups(self, aid):
        self._addon(aid)
        return {"backups": list_backups(aid)}

    def api_addon_restore(self, aid):
        addon = self._addon(aid)
        backup_id = self.body().get("backup_id", "")
        self._require_idle_unless_forced("Stop playback before restoring a backup")
        should_stop = self._backup_should_stop()
        try:
            return restore_backup(addon, backup_id, should_stop=should_stop)
        except BackupAborted as exc:
            # Raised while taking the undo snapshot, before the live folder was touched.
            raise self._backup_aborted(exc, should_stop, "restore's undo snapshot") from None
