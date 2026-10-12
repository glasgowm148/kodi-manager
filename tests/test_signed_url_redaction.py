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
