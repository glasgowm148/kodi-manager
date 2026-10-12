# Python library

Download the Python wheel from [release assets](https://github.com/glasgowm148/kodi-manager/releases/tag/v0.7.27)
and [verify it against `SHA256SUMS`](setup.md#verify-the-download). Create a **Python 3.9+** virtual
environment before installing; reuse an existing suitable one instead of replacing it.

On macOS/Linux, from the download folder:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install ./kodi_manager-0.7.27-py3-none-any.whl
```

On Windows (PowerShell):

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .\kodi_manager-0.7.27-py3-none-any.whl
```

Run the Python examples below with that environment's interpreter (`.venv/bin/python` or
`.venv\Scripts\python.exe`), or activate it before running `python`.
The installable Kodi service is a separate ZIP;
follow [setup](setup.md) if you also need the dashboard/API running on the TV.

## Connect to the running service

The same code ships as a Python library with no dependencies (Python 3.9+), for scripts and MCP
clients such as [nvidia-MCP](https://github.com/glasgowm148/nvidia-MCP).

```python
import os
from kodi_manager import ManagerClient

manager = ManagerClient("http://192.168.1.50:8765", os.environ["KODI_MANAGER_TOKEN"])
print(manager.status()["service_version"])
print(manager.pipeline().get("summary", {}).get("primary_player"))
```

`ManagerClient` also covers health, add-ons, settings, sources, folder browsing and layout
preview/apply; writes need `allow_writes=True`. The [API guide](api.md) lists every endpoint.

## Install from source and parse settings offline

```sh
git clone --branch v0.7.27 https://github.com/glasgowm148/kodi-manager.git
cd kodi-manager
python3 -m venv .venv
.venv/bin/python -m pip install .
```

On Windows use `py -3 -m venv .venv` and `.\.venv\Scripts\python.exe -m pip install .`.

```python
from kodi_manager import parse_schema, flatten_settings

addon = "addon/service.kodi.addonadmin"
schema = parse_schema(addon + "/settings.xml", addon)
settings = flatten_settings(schema)  # Defaults; secret-like values are masked.
```

Run this example from the cloned repository root. To include saved values for an installed add-on,
pass its private settings XML as `user_settings_path`; keep that file outside source control.

`ManagerClient`, `parse_schema` and `flatten_settings` are the public interface. Modules such as
`server` and `widget_cache` expect Kodi's runtime and may change before 1.0.

## Access and privacy

Supply the active profile's Manager token through private environment/configuration, never in source.
The service's API returns stored settings, including secrets; do not print full settings responses.
`ManagerClient(..., allow_writes=True)` also requires **Enable writes** inside Kodi.
Catch `kodi_manager.ManagerError` and inspect its `code` / `status` for refusals. Inspect state after a timeout
before retrying a mutation. Folder previews run installed provider code and may contact its services.

Use [API](api.md) for endpoint contracts and [Contributing](../CONTRIBUTING.md) for development.
