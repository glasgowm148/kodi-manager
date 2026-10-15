# Install Kodi Manager

Use your TV remote to install Kodi Manager, then open its dashboard on your phone or computer.
These steps work inside Kodi on Shield, Android TV, Google TV and Android-based Fire TV / Firestick.
Kodi must already be installed. Apple TV uses the same installation steps, but support is
[experimental](apple-tv.md).

You need:

- Kodi 19 or newer, with internet access.
- A phone or computer on the same home network as the TV.
- A few minutes with nobody watching anything on the TV.

No computer commands or debugging settings are needed for this dashboard.
Kodi Manager is currently preview software; this repository supplies preview updates.
If you already have a customized Manager installation, [back it up](recovery.md) before upgrading.

## 1. Add the download source — inside Kodi

1. Open **Kodi**, then **Settings** (the gear icon).
2. Open **File manager** → **Add source**. You may need to select Add source twice.
3. Select **<None>** and enter this address exactly, including `https://`:

   ```text
   https://glasgowm148.github.io/kodi-manager/
   ```

4. Select **OK**. For the source name, enter **Kodi Manager**, then select **OK** again.

This gives Kodi a place to download the repository installer. You do not need to copy a file
onto the TV. A GitHub project address is different from the source address above.

## 2. Install the repository, then Kodi Manager — inside Kodi

1. Open **Settings** → **System** → **Add-ons**.
2. Turn on **Unknown sources** and accept Kodi's warning. If the option is hidden, select the
   settings level at the bottom left until it says **Standard** or **Expert**.
3. Return to Kodi's home screen. Open **Add-ons**, then select the **open-box icon** at the top left.
   This opens the add-on browser. Menu positions can vary with your skin.
4. Select **Install from zip file**. Accept the update notice if shown.
5. Select **Kodi Manager**, then **repository.kodi-manager.zip**.
6. Wait for the **repository installed** notification.
7. Select **Install from repository** → **Kodi Manager Repository (preview)** → **Services** →
   **Kodi Manager** → **Install**. Accept the dependency list if Kodi shows one.
8. Wait for the **Kodi Manager installed** notification.

The ZIP in step 5 installs the repository once. Step 7 installs the actual dashboard add-on.
Future updates follow Kodi's add-on update settings. To choose updates yourself, open Kodi Manager's
add-on information page and turn **Auto-update** off.

## 3. Enable dashboard access

1. In Kodi, open **Settings** → **Add-ons** → **My add-ons** → **Services** → **Kodi Manager**.
2. Select **Configure**, then the **Dashboard** tab.
3. Turn on **Allow LAN access**. This lets your phone or computer reach the dashboard.
4. Leave **Enable writes** off for now. You can turn it on later to edit settings.
5. Select **OK** to save. You do not need to restart Kodi.

## 4. Open the dashboard on your phone or computer

<a id="connect--on-the-tv"></a>

1. Return to **Kodi's home screen**.
2. Open **Add-ons** → **Video add-ons** → **Kodi Manager**. Select the tile directly.
3. Select **Open the dashboard on another device**. The TV shows an address and an access token.
4. On your phone or computer, open a browser and enter the displayed address, starting with `http://`.
   Use the address on your TV, not an example from a guide.
5. Enter the displayed access token and sign in. Keep the token private, like a password.

Keep Kodi open while using the dashboard. Seeing its login page means the dashboard is reachable.
You can now inspect your setup. To make changes, return to step 3 and turn on **Enable writes**.

## Only Configure is available

The add-on information page under **My add-ons** is different from Kodi Manager's menu.
First return to the home screen and follow step 4 above.

If the tile is missing or still will not open:

1. Open **Settings** → **Add-ons** → **My add-ons** → **Services** → **Kodi Manager** → **Configure**.
2. Under **Dashboard**, select **Auth token**. Replace the masked value with your own private,
   random token, preferably at least 32 letters and digits from a password manager. Keep a private copy.
3. Turn on **Allow LAN access**, leave **Enable writes** off, then select **OK**.
4. Find the TV's IP address in its network settings. The [device guide](https://github.com/glasgowm148/nvidia-MCP/blob/main/docs/android-tv.md)
   shows where to look; you only need its “Find the IP address” step for this dashboard.
5. Open `http://YOUR_TV_IP:8765` in your browser, replacing `YOUR_TV_IP` with that address.
   If you changed Dashboard's port, use that port instead. Sign in with the token you saved.

Changing the token signs out clients using the old token. Leaving it blank generates a new one;
you would still need to find its value. If this fails, report your device, Kodi version, skin
and the menu step that failed. Exclude the token from screenshots.

## Everyday use and updates

- **Another browser:** once signed in, use **Advanced** → **Connection** → **Copy sign-in link**.
  Treat that link like a password. Use **Forget token in this browser** on a shared device.
- **Kodi profiles:** each profile can have its own access token and write setting. After switching,
  sign in with the token for the profile now open on the TV.
- **Updates:** repository installations use Kodi's update settings. To check manually, open the
  add-on browser's left sidebar and select **Check for updates**.
- **Existing ZIP installation:** install the repository using steps 1–2, then select Kodi Manager
  from that repository. Back up private modifications first; public updates replace add-on code.

Use a trusted home network. The dashboard uses plain HTTP; keep tokens, links and backups private.

## Android TV and Fire TV

The installation above is the same on Shield, Google TV, Android TV and Android-based Fire OS.
You do not need ADB debugging, Android's “Install unknown apps” permission or a file-transfer app
for repository installation. **Unknown sources inside Kodi** is the setting used here.

Some newer Fire TV devices use **Vega OS**. These Android instructions do not support Vega OS;
check your model in [Amazon's device/OS table](https://developer.amazon.com/docs/fire-tv/fire-os-overview.html).
Fire OS and Google TV hardware validation is still pending; see [compatibility](compatibility.md).
On low-memory sticks, start with a few cached rows and manual refresh.

## Optional assistant setup or manual installation

For an assistant to control or diagnose the TV, follow
[nvidia-MCP's TV setup](https://github.com/glasgowm148/nvidia-MCP/blob/main/docs/setup.md).
That separate setup needs debugging and Kodi remote control.

For offline/pinned ZIPs, checksums, file transfer and agent connection details, use
[advanced installation](setup-agent.md). For problems, use [troubleshooting](troubleshooting.md).
