# SpinJam on a Samsung Frame TV (Tizen)

This folder is a small Tizen web app for a Samsung TV. It is **not** part of the HACS integration. HACS installs `custom_components/spinjam` only. You sideload this app onto the TV yourself, then SpinJam launches it through the Samsung TV media player you already use in Home Assistant.

The app draws the now-playing screen itself. It does not load a Lovelace dashboard, so Home Assistant's header and sidebar never appear.

Nothing in the app is tied to a particular TV, address, or entity id. On each connection it asks Home Assistant for the entity registry and keeps the entities whose platform is `spinjam`.

## What the app does

- First launch shows a settings screen. Enter the Home Assistant base address (`http://host:8123`) and a long-lived access token. **Save and connect** stores both in `localStorage`.
- Later launches connect to `/api/websocket` with that token and open the now-playing screen.
- The app subscribes to state changes for the SpinJam now-playing media player, the lyrics switch, and the lyric-delay number. Those are chosen by translation key (`now_playing`, `lyrics`, `lyric_offset`), not by a fixed entity id.
- **Lyrics on:** album art on the left, synced scrolling lyrics on the right, current line highlighted. The lyric delay (positive = later) is applied on the TV, and the playhead keeps moving between websocket updates.
- **Lyrics off:** one widescreen view, a centred square cover over a blurred copy of that cover, with the title, artist, album, and a progress bar.
- **Idle:** a **Waiting for music** screen.
- **Back** on that waiting screen returns to settings. A **long press of Back** opens settings while music is playing. **Exit** closes the app.
- The screensaver is turned off with `webapis.appcommon.setScreenSaver`, and `tizen.power` asks the screen and CPU to stay awake. Both are applied again every 30 seconds.
- If the websocket closes, the network drops, or Home Assistant does not answer, the app shows a reconnecting message and tries again with a short backoff. It tries again when the network returns. A rejected token opens settings instead of retrying.

Album art uses `artwork_hd` when SpinJam has one, otherwise `entity_picture`. Relative picture paths (including `/api/media_player_proxy/...`) are loaded from the Home Assistant address you entered. The access token is sent only to that address.

`SpinJam.wgt` in this folder is the packaged widget (a zip of `config.xml`, `index.html`, `css/app.css`, `js/logic.js`, `js/app.js`, and `icon.png`). It is **unsigned**. A TV rejects an unsigned widget. Sign it with your own Tizen certificate before installing. Rebuild the unsigned zip after editing the app:

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

Open **SpinJam** from the TV's app list.

1. In Home Assistant, create a user that is **not** an administrator. The user only needs to read the SpinJam entities (now playing, the lyrics switch, and the lyric delay).
2. Sign in as that user and create a **long-lived access token** (profile → security → long-lived access tokens).
3. On the TV, enter the Home Assistant base address, such as `http://host:8123`, and paste the token. **Save and connect.**

Trusted networks are no longer required. Do not put the token in a URL. The TV stores it in `localStorage` and sends it only on the websocket, and on artwork requests to that same Home Assistant address.

A LAN `http://` address works. If you use HTTPS with a certificate the TV does not trust, the connection fails and the app keeps reconnecting.

## What it reads

From the entity registry (`config/entity_registry/list_for_display`, platform `spinjam`):

| Translation key | Entity | Used for |
| --- | --- | --- |
| `now_playing` | media player | Title, artist, album, art, position, synced lyrics |
| `lyrics` | switch | Lyrics on or off (`on` / `off`) |
| `lyric_offset` | number | Lyric delay in milliseconds, positive = later |

Now-playing attributes: `media_title`, `media_artist`, `media_album_name`, `media_position`, `media_position_updated_at`, `media_duration`, `entity_picture`, `artwork_hd`, `artwork_next`, `lyric_lines` (`t` in seconds, `text`, optional `words`), `lyric_offset_ms`, `lyrics_enabled`, `lyrics_status`, `lyrics_source`, `lyric_current`.

`lyric_lines` already carries the LRC times, so the TV does not need a separate lyrics command. The delay number is applied once on the TV. `lyric_offset_ms` is used only when that number is missing. `lyrics_enabled` is used only when the lyrics switch is missing.

## Launch it from Home Assistant

After the app is installed:

1. The Samsung TV integration must already provide a media player for this TV.
2. SpinJam → Configure → **Displays**: choose that media player. The same list is the SpinJam display selector.
3. **Tizen application id**: the id from your certificate, such as `AbCdEfGhIj.Display`. Leave it blank if this entry only uses Cast.
4. Leave **Built-in display launch** on.
5. Turn on the SpinJam Cast switch, or call `spinjam.start`.

SpinJam turns the TV on if it is off, then starts the application id as an app. It does not use a Cast device.

Turning the switch off sends the Home key (`KEY_HOME`) so the app closes and the panel stays on. **Power off display when stopping** powers the TV off instead.

Limitations are listed in [TV cast](../docs/TV_CAST.md#samsung-frame-tv-tizen).
