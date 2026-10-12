"""The NVIDIA-only exit workaround must not arm on a generic Android / Fire OS box."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from kodi_manager import service


@pytest.mark.parametrize('android,nvidia,version,enabled,expected', [
    (True, False, '22.0-RC1', True, False),  # Fire OS / Google TV, even with opt-in saved
    (True, False, '21.3', True, False),
    (False, True, '22.0-RC1', True, False),
    (True, True, '22.0-RC1', False, False),
    (True, True, '22.0-RC2', True, False),
    (True, True, '22.0-RC1', True, True),
])
def test_exit_workaround_device_gate(android, nvidia, version, enabled, expected):
    runtime = SimpleNamespace(getCondVisibility=lambda _: android, getInfoLabel=lambda _: version)
    with patch.object(service, 'xbmc', runtime), patch.object(service.os.path, 'isfile', return_value=nvidia):
        assert service.shield_exit_supported({'shield_exit_workaround': enabled}) is expected
