"""Preserve useful item actions when JSON-RPC strips a source's context menu."""
from urllib.parse import parse_qs, urlencode, urlsplit


def pov_target(item, media_type):
    path = item.get('file') or item.get('url') or ''
    parsed = urlsplit(path)
    if parsed.netloc not in ('plugin.video.pov', 'plugin.video.tmdb.bingie.helper'):
        return None
    query = parse_qs(parsed.query)
    tmdb_id = query.get('tmdb_id', [''])[0]
    kind = 'movie' if media_type == 'movie' else 'tvshow' if media_type in ('tvshow', 'season', 'episode') else ''
    if not kind or not tmdb_id.isdigit() or int(tmdb_id) <= 0:
        return None
    return kind, tmdb_id


def _pov(params):
    return 'RunPlugin(plugin://plugin.video.pov/?%s)' % urlencode(params)


def pov_play_actions(item, media_type, tmdb_id):
    """POV's own long-press entries that JSON-RPC drops: pick a source by hand, Options, Extras."""
    if urlsplit(item.get('file') or item.get('url') or '').netloc != 'plugin.video.pov':
        return []
    query = parse_qs(urlsplit(item.get('file') or item.get('url') or '').query)
    actions = []
    if media_type == 'movie':
        actions.append(('Select source', _pov({'mode': 'play_media', 'mediatype': 'movie', 'tmdb_id': tmdb_id, 'autoplay': 'false'})))
        actions.append(('Options...', _pov({'mode': 'options_menu_choice', 'mediatype': 'movie', 'tmdb_id': tmdb_id, 'is_widget': 'true'})))
        actions.append(('Extras...', _pov({'mode': 'extras_menu_choice', 'mediatype': 'movie', 'tmdb_id': tmdb_id, 'is_widget': 'true'})))
    elif media_type == 'episode':
        season = query.get('season', [str(item.get('season', ''))])[0]
        episode = query.get('episode', [str(item.get('episode', ''))])[0]
        if season.isdigit() and episode.isdigit():
            actions.append(('Select source', _pov({'mode': 'play_media', 'mediatype': 'episode', 'tmdb_id': tmdb_id,
                                                   'season': season, 'episode': episode, 'autoplay': 'false'})))
            actions.append(('Options...', _pov({'mode': 'options_menu_choice', 'content': 'episode', 'tmdb_id': tmdb_id,
                                                'season': season, 'episode': episode, 'is_widget': 'true'})))
        actions.append(('Extras...', _pov({'mode': 'extras_menu_choice', 'mediatype': 'tvshow', 'tmdb_id': tmdb_id, 'is_widget': 'true'})))
    elif media_type in ('tvshow', 'season'):
        actions.append(('Options...', _pov({'mode': 'options_menu_choice', 'mediatype': 'tvshow', 'tmdb_id': tmdb_id, 'is_widget': 'true'})))
        actions.append(('Extras...', _pov({'mode': 'extras_menu_choice', 'mediatype': 'tvshow', 'tmdb_id': tmdb_id, 'is_widget': 'true'})))
    return actions


def item_actions(item, media_type, source):
    target = pov_target(item, media_type)
    if not target:
        return {}, []
    kind, tmdb_id = target
    play_actions = pov_play_actions(item, media_type, tmdb_id)
    source_query = parse_qs(urlsplit(source).query)
    watchlist = source_query.get('action', [''])[0] in ('trakt_watchlist', 'trakt_watchlist_lists') or source_query.get('info', [''])[0] == 'trakt_watchlist'
    params = {'mode': 'manager_watchlist', 'mediatype': kind, 'tmdb_id': tmdb_id, 'action': 'remove' if watchlist else 'add'}
    actions = [('Remove from watchlist' if watchlist else 'Add to watchlist',
                'RunPlugin(plugin://plugin.video.pov/?%s)' % urlencode(params))]
    if kind == 'tvshow':
        params = {'mode': 'manager_show', 'mediatype': kind, 'tmdb_id': tmdb_id}
        actions.append(('Browse show', 'RunPlugin(plugin://plugin.video.pov/?%s)' % urlencode(params)))
    if media_type == 'episode':
        query = parse_qs(urlsplit(item.get('file') or item.get('url') or '').query)
        season = query.get('season', [item.get('season', '')])[0]
        episode = query.get('episode', [item.get('episode', '')])[0]
        if str(season).isdigit() and str(episode).isdigit() and int(episode) > 0:
            params = {'mode': 'manager_seen', 'tmdb_id': tmdb_id, 'season': season, 'episode': episode}
            actions.append(('Already watched this', 'RunPlugin(plugin://plugin.video.pov/?%s)' % urlencode(params)))
    return {'km_tmdb_id': tmdb_id, 'km_mediatype': kind}, actions + play_actions
