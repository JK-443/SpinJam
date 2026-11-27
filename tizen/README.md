# SpinJam on a Samsung Frame TV (Tizen)

This folder is a small Tizen web app for a Samsung TV. It is **not** part of the HACS integration. HACS installs `custom_components/spinjam` only. You sideload this app onto the TV yourself, then SpinJam launches it through the Samsung TV `media_player` you already use in Home Assistant.

The app opens one Home Assistant dashboard address full screen. You type that address on the TV the first time it runs. The TV stores it in `localStorage`. Nothing in the app is tied to a particular TV, address, or Home Assistant entity.

## What the app does

- First launch shows a settings screen. Move with the remote, press Enter to type, then **Save and open**.
- Later launches open that address in a full-screen iframe.
- **Back** switches between the dashboard and the settings screen. **Exit** closes the app.
- The screensaver is turned off with `webapis.appcommon.setScreenSaver`, and `tizen.power` asks the screen and CPU to stay awake. Both are applied again every 30 seconds.
- If the iframe never loads, the page errors, or the network drops, the app shows a reconnecting message and reloads with a short backoff. It tries again when the network returns.

`SpinJam.wgt` in this folder is the packaged widget (a zip of `config.xml`, `index.html`, `css/app.css`, `js/app.js`, and `icon.png`). It is **unsigned**. A TV rejects an unsigned widget. Sign it with your own Tizen certificate before installing. Rebuild the unsigned zip after editing the app:

```bash
python3 package_wgt.py
```

`tizen package` rewrites the placeholder package id in `config.xml` (`SpinJamDsp`) to the 10-character id from your certificate. The id you enter in SpinJam options is the id **after** that rewrite, not the placeholder.

## Install on the TV

### 1. Turn on developer mode

1. On the TV, open **Settings → Support → About This TV** (on some models: **All Settings → Support → Device Care → About This TV**).
2. Highlight the software or network information row and press Enter several times until **Developer mode** appears.
3. Turn Developer mode on. Enter the IP address of the computer that will run Tizen Studio or `sdb`. Confirm.
4. Reboot the TV when it asks. After the reboot, open the same screen and confirm Developer mode is still on. Note the TV's **DUID** and its IP address. You will need both.

### 2. Install Tizen Studio or the CLI

Either of these works:

- **Tizen Studio** with the **TV Extensions** package (Certificate Manager, `sdb`, and the `tizen` CLI), or
- The **Tizen Studio CLI** installer plus the same TV extension, so `tizen` and `sdb` are on your `PATH`.

### 3. Create a certificate

1. Open **Tools → Certificate Manager → Samsung** and create a TV certificate profile. Samsung asks you to sign in so it can issue the distributor certificate.
2. Add this TV's **DUID** to the certificate. A package signed without that DUID will not install.
3. Remember the profile name. Certificate Manager also shows the 10-character package id. The installed application id will look like `AbCdEfGhIj.Display` (that prefix, a dot, then `Display`).

### 4. Package and install the widget

Connect the TV, then sign and install from this directory. Replace the angle-bracket placeholders with your profile name, the TV address, and the device name `sdb devices` prints.

```bash
sdb connect <tv-ip>
sdb devices
python3 package_wgt.py
tizen package -t wgt -s <profile-name> -- .
tizen install -n SpinJam.wgt -t <device-name>
```

Tizen Studio alternative: **File → Open Projects from File System**, choose this `tizen` folder, then right-click the project and choose **Build Signed Package**. Install the signed `.wgt` it writes with `tizen install`, or with the Studio device manager.

If install reports a certificate error, the DUID is missing from the certificate. Add it, package again, and install again.

Do not commit the signed widget. It is tied to your certificate. The unsigned `SpinJam.wgt` in git is only the app package.

If packaging refuses `http://tizen.org/privilege/power`, delete that privilege line from `config.xml`, package again, and rebuild the zip. The screensaver call does not need it. Screen-stay-awake is weaker without `tizen.power`, and the screensaver API still runs.

### 5. First launch on the TV

Open **SpinJam** from the TV's app list. Enter the dashboard address, for example:

```text
http://homeassistant.local:8123/spinjam-tv/now
```

Use the path you configured in SpinJam (`dashboard_path` / `view_path`, defaults `spinjam-tv` / `now`). Create that dashboard first with `spinjam.create_dashboard` if it does not exist. See [TV cast](../docs/TV_CAST.md).

The TV must be able to open that address. A LAN `http://` URL works for this app. Cast cannot load plain HTTP; this app can. If you use HTTPS with a certificate the TV does not trust, the iframe stays blank and the app keeps reconnecting.

## Home Assistant login

The iframe is a normal page load. It does not share cookies with the TV's web browser.

### Trusted networks (this is the one that works)

Add the TV as a trusted network so Home Assistant signs that address in without a password. Keep the normal `homeassistant` provider in the list as well, or you can lock yourself out of the UI.

```yaml
homeassistant:
  auth_providers:
    - type: trusted_networks
      trusted_networks:
        - <tv-ip>/32
      trusted_users:
        <user-id>:
          - <tv-ip>
      allow_bypass_login: true
    - type: homeassistant
```

`<tv-ip>` is the TV on your LAN. `/32` trusts that address only. `<user-id>` is the id shown under **Settings → People**, not a name you make up here. Restart Home Assistant after editing `configuration.yaml`.

The address you type on the TV has to be one the TV can reach, such as `http://homeassistant.local:8123/spinjam-tv/now`.

### Long-lived access token in the URL

Not supported. A long-lived access token authenticates the REST API and the websocket when the client sends it as a bearer token. The Lovelace dashboard does not read a token from the query string, so `?token=` (or any other token pasted into the address) does not sign the iframe in. The TV would still show the login page, and the app would store that address in `localStorage`. Do not put a token in the URL. Use trusted networks.

## Launch it from Home Assistant

After the app is installed:

1. The Samsung TV integration must already provide a `media_player` for this TV.
2. SpinJam → Configure → **Displays**: choose that entity, for example `media_player.living_room_frame`. The same list is `select.spinjam_display`.
3. **Tizen application id**: the id from your certificate, such as `AbCdEfGhIj.Display`. Leave it blank if this entry only uses Cast.
4. Leave **Built-in display launch** on.
5. Turn on `switch.spinjam_cast`, or call `spinjam.start`.

SpinJam turns the TV on if it is off, then calls `media_player.play_media` with media type `app` and that application id. It does not use a Cast device.

Turning the switch off sends the Home key (`KEY_HOME`) so the app closes and the panel stays on. **Power off display when stopping** powers the TV off instead.

Limitations are listed in [TV cast](../docs/TV_CAST.md#samsung-frame-tv-tizen).
