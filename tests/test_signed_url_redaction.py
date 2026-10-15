"""Synthetic signed CDN URLs must keep diagnostic context while hiding credentials."""
import pytest

from kodi_manager.validation import mask_secrets_in_text


@pytest.mark.parametrize('key', ['__gda__', 'HDNEA', 'hdnts', 'Signature', 'Policy', 'Key-Pair-Id',
                                'X-Amz-Signature', 'X-Goog-Signature'])
def test_signed_cdn_query_fields_are_masked_without_losing_url_boundaries(key):
    raw = 'Failed <https://cdn.example.invalid/manifest.mpd?quality=hd&%s=fixture-value>' % key
    masked = mask_secrets_in_text(raw)
    assert masked == 'Failed <https://cdn.example.invalid/manifest.mpd?quality=hd&%s=***>' % key
    assert mask_secrets_in_text(masked) == masked


SECRET = 'S3cr3tVALUE9x'


@pytest.mark.parametrize('text', [
    '"access_token": "%s"' % SECRET,
    '{"api_key": "%s"}' % SECRET,
    "{'api_key': '%s'}" % SECRET,
    "headers={'token':'%s'}" % SECRET,
    'params={"refresh_token":"%s"}' % SECRET,
    'trakt_token=%s' % SECRET,
    'tmdb_api_key=%s' % SECRET,
    'tmdb.api_key: %s' % SECRET,
    'rd-token = "%s"' % SECRET,
    'http://h/x?a=1&tmdb_api_key=%s&b=2' % SECRET,
    'smb://user:%s@nas/share' % SECRET,
    'ftp://u:%s@h/' % SECRET,
    'nfs+tls://u:%s@h/export' % SECRET,
    'https://h/x.m3u8|User-Agent=a&Authorization=Bearer%%20%s' % SECRET,
    'Authorization=Bearer+%s' % SECRET,
])
def test_quoted_prefixed_and_non_http_credentials_are_masked(text):
    masked = mask_secrets_in_text(text)
    assert SECRET not in masked
    assert mask_secrets_in_text(masked) == masked


def test_redact_masks_secrets_inside_logged_structures():
    from kodi_manager.validation import redact
    out = redact({'msg': 'payload {"access_token": "%s", "page": 2}' % SECRET, 'items': ['smb://u:%s@nas/' % SECRET]})
    assert SECRET not in str(out)
    assert '"page": 2' in out['msg']
    assert out['items'] == ['smb://***@nas/']


@pytest.mark.parametrize('text', [
    'keyboard=1 keymap: default monkey=3 turkey: 4 hotkey=F1',
    'Loading keymap.xml from special://xbmc/system/keymaps/',
    'special://home/addons/skin.bingie/ user@example.com',
    'tokenizer=fast secretary: Ann passwords_seen=3',
])
def test_ordinary_log_words_are_not_masked(text):
    assert mask_secrets_in_text(text) == text


@pytest.mark.parametrize('unit', ['a_', 'a.', 'a@', 'x://', 'http://a@', 'Bearer ', 'Bearer%20', '"token": "',
                                  'key=', 'a', 'aaaa:', 'tmdb_api_key=', 'smb://u:p@'])
def test_masking_stays_fast_on_large_adversarial_text(unit):
    import time
    text = unit * (100000 // len(unit) + 1)
    started = time.monotonic()
    mask_secrets_in_text(text)
    assert time.monotonic() - started < 5.0
