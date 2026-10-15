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

## Using an AI assistant?

- **Set up nvidia-MCP first.**
  - Follow [its TV setup guide](https://github.com/glasgowm148/nvidia-MCP/blob/main/docs/setup.md).
  - Wait for your agent to confirm the TV and Kodi connection works.
- **Ask the agent to add Kodi Manager.**
  - Use [the installation request](https://github.com/glasgowm148/nvidia-MCP/blob/main/docs/companion.md#ask-your-agent-to-install-kodi-manager).
  - The agent handles preparation and connection checks. Some Kodi installer or permission screens
    may still need your input on the TV.

If you only want the browser dashboard, follow the remote-control steps below.

## 1. Add the download source — inside Kodi

- **Open the source dialog.**
  - Open **Kodi → Settings** (gear icon) → **File manager → Add source**.
  - You may need to select Add source twice. Select **`<None>`**.
- **Enter the source details.**
  - **Address:** `https://glasgowm148.github.io/kodi-manager/`
  - **Name:** `Kodi Manager`
  - Use the address exactly, including `https://` and the final `/`.
- **Save.**
  - Select **OK** after entering the address, then **OK** again after naming the source.

## 2. Install the repository, then Kodi Manager — inside Kodi

- **Allow the repository.**
  - Open **Settings → System → Add-ons**.
  - Turn on **Unknown sources** and accept Kodi's warning.
  - If hidden, change the settings level at the bottom left to **Standard** or **Expert**.
- **Install the repository.**
  - Return home. Open **Add-ons**, then the **open-box icon** at the top left.
  - Select **Install from zip file** and accept the update notice if shown.
  - Select **Kodi Manager → repository.kodi-manager.zip**.
  - Wait for the **repository installed** notification.
- **Install Kodi Manager.**
  - Select **Install from repository → Kodi Manager Repository (preview)**.
  - Open **Services → Kodi Manager → Install**.
  - Accept the dependency list if shown, then wait for **Kodi Manager installed**.

The repository is installed once. Future updates follow Kodi's update settings;
turn **Auto-update** off on Kodi Manager's add-on information page if you prefer manual updates.

## 3. Enable dashboard access

- **Open Kodi Manager's settings.**
  - Go to **Settings → Add-ons → My add-ons → Services**.
  - Select **Kodi Manager → Configure → Dashboard**.
- **Set access.**
  - **Allow LAN access:** on, so your phone or computer can connect.
  - **Enable writes:** off while you first inspect your setup.
  - Select **OK** to save. No restart is needed.

## 4. Open the dashboard on your phone or computer

<a id="connect--on-the-tv"></a>

- **On the TV:**
  - Return to Kodi's home screen.
  - Open **Add-ons → Video add-ons → Kodi Manager**. Select the tile directly.
  - Select **Open the dashboard on another device**.
  - The TV shows the dashboard address and access token.
- **On your phone or computer:**
  - Open the displayed address in your browser, starting with `http://`.
  - Enter the displayed token and sign in. Keep the token private, like a password.
- **While using the dashboard:**
  - Keep Kodi open on the TV.
  - To edit settings, return to step 3 and turn on **Enable writes**.

## Only Configure is available

The add-on information page under **My add-ons** is different from Kodi Manager's menu.
First return to the home screen and follow step 4 above.

If the tile is missing or still will not open:

- **Set a token in Kodi Manager's settings.**
  - Open **Settings → Add-ons → My add-ons → Services → Kodi Manager → Configure**.
  - Under **Dashboard**, select **Auth token** and replace the masked value.
  - Use a private random token, preferably at least 32 letters and digits from a password manager.
  - Keep a private copy. Turn on **Allow LAN access**, leave **Enable writes** off, then select **OK**.
- **Sign in from your browser.**
  - Find the TV's IP using the “Find the IP address” step in the
    [device guide](https://github.com/glasgowm148/nvidia-MCP/blob/main/docs/android-tv.md).
  - Open `http://YOUR_TV_IP:8765`, replacing `YOUR_TV_IP` with that address.
  - If you changed Dashboard's port, use that port instead.
  - Sign in with the token you saved.

Changing the token signs out clients using the old token. Leaving it blank generates a new one;
you would still need to find its value. If this fails, report your device, Kodi version, skin
and the menu step that failed. Exclude the token from screenshots.

## Everyday use and updates

- **Another browser**
  - Use **Advanced → Connection → Copy sign-in link** once signed in.
  - Treat the link like a password. Use **Forget token in this browser** on a shared device.
- **Kodi profiles**
  - Each profile can have its own token and write setting.
  - After switching, sign in with the token for the profile now open on the TV.
- **Updates**
  - Repository installations follow Kodi's update settings.
  - To check manually, open the add-on browser's left sidebar → **Check for updates**.
- **Existing ZIP installation**
  - Back up private modifications first; public updates replace add-on code.
  - Install the repository using steps 1–2, then select Kodi Manager from that repository.

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
