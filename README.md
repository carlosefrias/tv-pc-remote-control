# TV Remote

Control the TV laptop (Linux Mint + Firefox over HDMI) from your phone.

- **Laptop** (`server/tvremote.py`): small Python server that uses only the standard library. When you pick a channel it closes all Firefox windows, reopens Firefox in **kiosk** mode on that channel's page, and puts the **video player itself in full screen**, so the TV shows only the video. It also controls the volume, stops playback and shuts the laptop down.
- **Phone** (`web/`): web app. It shows a grid of channels plus volume, stop and power buttons, and has an edit mode for the channel list. It works on Android and iOS. Add it to the home screen to use it like an app. It reaches the laptop **through the internet**, so it works even when the Wi-Fi isolates devices from each other, as the home 4G router does. See [How the phone reaches the laptop](#how-the-phone-reaches-the-laptop).

## Install (on the laptop)

```bash
git clone <this repo> ~/tv-pc-home-remote
cd ~/tv-pc-home-remote
./install.sh
```

Run it as your normal user, not with `sudo`. It asks for your password once. The installer:
- installs `qrencode`, which draws the QR code for the phone, and `wmctrl`, which helps move Firefox to the TV screen
- adds an autostart entry, so the server starts every time you log in to the desktop
- creates `~/.config/tv-remote/` (`config.json` holds the token and settings, `channels.txt` holds the channels)
- opens the server port in the firewall, if the firewall (`ufw`) is on
- shows the **QR code** for your phone (see below)

## How to use

### 1. Connect your phone (once)

The phone app is a web page, so there's nothing to install from an app store. The phone can be on any network: the home Wi-Fi, or mobile data.

1. On the laptop, run `./install.sh`, or `./show-qr.sh` if it is already installed. A QR code appears in the terminal, on the TV:

   ```
     Scan this with the phone's camera (works on any network, through the internet):

     █▀▀▀▀▀█ ▄▀▄█▀ █▀▀▀▀▀█
     █ ███ █ ▀█▄▀▄ █ ███ █
     ...

     Link: https://carlosefrias.github.io/tv-pc-remote-control/#k=AbC123xyz...
   ```

2. **Scan the QR code with the phone's camera** and tap the link that appears. If the camera app doesn't recognise QR codes, use Google Lens.
3. The channel grid opens, and next to **TV** it shows **● ligado**. Turn it into an app icon:
   - **Android (Chrome):** menu **⋮** → **Add to Home screen** (or **Install app**)
   - **iPhone (Safari):** **Share** → **Add to Home Screen**

From now on, just tap the **TV** icon on the phone's home screen. To add another phone, for example for someone else in the house, run `./show-qr.sh` on the laptop and scan the code again.

The QR code contains a secret key (after `#k=`), which the phone remembers. **Keep the code private: whoever scans it can control the TV.** To revoke all phones, delete `relay_secret` from `~/.config/tv-remote/config.json`, restart the server (`./install.sh`), and scan the new code with each phone.

### 2. Watch TV

| On the phone | What happens on the TV |
|---|---|
| Tap a channel | Firefox closes and reopens on that channel, with the video player full screen and sound on. The tile is marked **● AO VIVO**. |
| 🔉 / 🔊 | Volume down / up |
| 🔇 | Mute / unmute |
| ⏹ | Stops: closes Firefox |
| ⏻ | Shuts down the laptop (asks for confirmation first) |
| **Editar** | Add, rename, reorder (↑ ↓) or delete channels, then **Guardar** |

### If it doesn't work

| Problem | Fix |
|---|---|
| "O portátil não respondeu" / **● sem resposta** | The laptop is off, has no internet, or the server isn't running. `./show-qr.sh` warns you if the server isn't running. Check `tail ~/.config/tv-remote/server.log`: it should say `relay: connected to https://ntfy.sh`. |
| "A hora do telemóvel está errada" | Set the phone's clock to automatic. Commands are only accepted if the phone and laptop clocks are within 5 minutes of each other. |
| "Limite diário de mensagens" | ntfy.sh allows 250 messages a day for all your devices together (see below). It resets the next day. |
| The page itself doesn't open | The phone has no internet, or the app page isn't published yet (see [Publishing the phone app](#publishing-the-phone-app)). |
| Using the old home-network link | `./show-qr.sh --local` shows it. It only works if the router lets Wi-Fi devices see each other, and the firewall must allow the port (`sudo ufw allow 8080/tcp`). |
| No QR code, only a link | Run `sudo apt install qrencode`, then `./show-qr.sh`. |
| A channel shows the whole page, not just the video | Pick it again. If it keeps happening, check the `fullscreen:` lines in the log. |
| The channel opens on the laptop's screen, not the TV | Check the `display:` lines in the log. If the TV wasn't detected, set `tv_display` to its output name (see `xrandr --listmonitors`). Check `wmctrl` is installed. |

## Channels

You can edit the channels from the phone (**Editar** button), or by hand in `~/.config/tv-remote/channels.txt`:

```
RTP 1 | https://www.rtp.pt/play/direto/rtp1
CNN Portugal | https://cnnportugal.iol.pt/direto
```

Each line is `Name | URL`, and the file order is the grid order. Changes are picked up right away, with no restart needed.

When new channels are added to the default list ([`server/channels.default.txt`](server/channels.default.txt)), add them to your own list with:

```bash
./update-channels.sh
```

It only adds the missing channels, at the end. Your own channels, names and order stay as they are.

### Channels in the default list

All of these are official, free live streams (in Portugal). Each was tested in Firefox with the full-screen helper:

| Channel | Page |
|---|---|
| RTP 1, RTP 2, RTP Notícias, RTP Memória, RTP Mundo, RTP África, RTP Madeira, RTP Açores, RTP Desporto 1 | `rtp.pt/play/direto/…` |
| CNN Portugal | `cnnportugal.iol.pt/direto` |
| ARTV Parlamento | `canal.parlamento.pt` |

RTP Desporto 1 only has pictures while an event is on.

Not included for now (checked in November 2026):

| Channel | Why |
|---|---|
| SIC, TVI (and V+, TVI Ficção, TVI Reality, TVI Internacional) | The live stream needs an account (OPTO / TVI Player). The player never starts in the TV's Firefox. |
| SIC Notícias | The free player at `sicnoticias.pt/agora` loads, but in tests it never received video. |
| CMTV, NOW | Need an account ("Iniciar sessão"). |
| Porto Canal | The site blocks automated browsers (Cloudflare). |
| Euronews | The player is in a frame and waits for a click. It could be supported later. |

Sites such as cxtv re-stream channels without the broadcasters' permission, so they are not used here.

## How the phone reaches the laptop

Many routers isolate Wi-Fi devices from each other ("AP isolation"), and 4G connections don't accept connections coming in from the internet. So the phone and the laptop talk through **[ntfy.sh](https://ntfy.sh)**, a free public message service that needs no account:

```
phone ──HTTPS──▶ ntfy.sh topic "cmd" ──stream──▶ laptop   (commands)
phone ◀──SSE──── ntfy.sh topic "state" ◀─HTTPS── laptop   (replies)
```

- **Only outgoing connections:** the laptop keeps one HTTPS connection open to ntfy.sh, so no ports or router settings are needed. In tests, a command took about 1 s from tap to confirmation.
- **One secret, created on the laptop:** `relay_secret` in `config.json`. The two topic names and the signing key are derived from it. It reaches the phone only inside the QR code, after the `#`, and browsers never send that part to any server.
- **Signed commands:** every message is signed with HMAC-SHA256. The laptop ignores messages with a wrong signature, messages older than 5 minutes, and repeated messages. Replies are signed too, and are not stored on ntfy.sh (`Cache: no`).
- **Not encrypted:** ntfy.sh can see the content of the messages, such as channel names and "play channel 3". There are no passwords or personal data in them.
- **Daily limit:** ntfy.sh allows **250 messages a day**, and the phone and laptop count together because they share the router's internet address. Opening the app or changing channel uses 2 messages, and a volume press uses 1. That's plenty for normal use.

The protocol is implemented in [`server/relay.py`](server/relay.py) on the laptop and in `RelayTransport` in [`web/app.js`](web/app.js) on the phone. To turn it off, set `"relay": false`. The phone then needs the home-network link (`./show-qr.sh --local`).

### Publishing the phone app

The phone app (the `web/` folder) is hosted on GitHub Pages at `https://carlosefrias.github.io/tv-pc-remote-control/` (setting `app_url` in `config.json`). The workflow [`.github/workflows/pages.yml`](.github/workflows/pages.yml) publishes it automatically on every push to `master`, so changes to `web/` go live a minute or two after `git push`.

One-time setup: in the repository's **Settings → Pages**, set **Source** to **GitHub Actions**.

The repository is public, but there are no secrets in it. The token, the relay key and `config.json` are created on the laptop, in `~/.config/tv-remote/`, and never committed.

## Which screen shows the channel

When the laptop and the TV form one extended desktop, Firefox would open on the laptop's own screen. So on every channel change, the server finds the TV and moves Firefox there before opening the channel:

1. **Finding the TV:** `xrandr --listmonitors` lists the screens. The TV is the external output (`HDMI-…`, `DP-…`) rather than the built-in panel (`eDP-…`, `LVDS…`). If there are several external screens, it picks the physically biggest. With a single screen, or mirrored screens, nothing needs to move.
2. **Moving Firefox:** through Marionette, the server moves the window to the TV's position and makes it full screen there. If the window manager refuses, plan B uses `wmctrl` (installed by `install.sh`).

The log shows the decision, for example `display: screens: eDP-1 1920x1080+0+0, HDMI-1 1920x1080+1920+0 -> TV is HDMI-1`, followed by `moved Firefox to the TV (HDMI-1)`.

To choose the screen yourself, set `tv_display` in `config.json` to the output name (see `xrandr --listmonitors`). Set it to `"none"` to turn this off. Moving windows needs the normal **X11** Cinnamon session; it may not work in the experimental Wayland session.

## How the player goes full screen

Firefox only lets a page go full screen after a real click, so the server controls Firefox through **Marionette**, Firefox's built-in remote-control protocol. It is enabled with `--marionette` and only listens on `localhost`. When you pick a channel:

1. Firefox starts on a blank page with the TV profile, and the server connects to it.
2. The server opens the channel page, then runs [`server/player_assist.js`](server/player_assist.js) in it about once a second. That script:
   - finds the biggest video on the page and puts its player into real full screen, which also hides the site's pop-ups;
   - unmutes the video, because many sites start muted;
   - starts the video if it is waiting for a click. It tries `play()` first, then one real click on the player. It never clicks while an ad is playing.
3. The server keeps checking (every 5 s after the first minute), so if anything takes the player out of full screen, it goes back.

This works with any site that uses a standard web video player, not just RTP and CNN. If Firefox can't be controlled within 15 s, the server falls back to opening the page normally in kiosk mode. To turn the feature off, set `fullscreen_player` to `false`.

It was tested in Firefox 149: RTP 1, RTP 2 and RTP Notícias go full screen and play within about 5–15 s, CNN Portugal within about 25 s. CNN builds its player slowly, and sometimes plays a pre-roll ad first.

## Settings (`~/.config/tv-remote/config.json`)

| key | default | meaning |
|---|---|---|
| `port` | `8080` | HTTP port |
| `token` | random | secret the phone must send; delete it to generate a new one |
| `firefox_cmd` | `firefox` | browser command |
| `kiosk` | `true` | full screen with no tabs or address bar (`false` opens a normal window) |
| `dedicated_profile` | `true` | uses a separate Firefox profile with autoplay allowed and no "restore session" prompt |
| `fullscreen_player` | `true` | puts only the video player in full screen (needs `dedicated_profile`) |
| `marionette_port` | `2828` | local port used to control Firefox |
| `tv_display` | `auto` | screen that shows the channel: `auto` (the external TV), an output name such as `HDMI-1`, or `none` |
| `relay` | `true` | control through the internet via ntfy (see above) |
| `relay_server` | `https://ntfy.sh` | ntfy server to use (could be self-hosted) |
| `relay_secret` | random | key shared with the phone through the QR code; delete it to revoke all phones |
| `app_url` | `https://carlosefrias.github.io/tv-pc-remote-control/` | where the phone app is published |
| `shutdown_cmd` | `["systemctl","poweroff"]` | command used by the power button |
| `volume_step` | `5%` | volume step (uses `pactl`, falls back to `amixer`) |

Restart the server after changing settings. The simplest way is to run `./install.sh` again.

## Run manually / debug

```bash
./show-qr.sh                        # QR code + link for the phone (internet)
./show-qr.sh --local                # home-network link instead
python3 server/tvremote.py          # run the server in the foreground
tail -f ~/.config/tv-remote/server.log
```

Each time the player's state changes, the log gets a line starting with `fullscreen:` showing whether it is full screen, playing, muted, or in an ad.

To leave kiosk mode on the laptop, press **Alt+F4**, or use ⏹ on the phone.

## API

Every call needs the `X-Token: <token>` header.

| method | path | body |
|---|---|---|
| GET | `/api/channels` | – |
| PUT | `/api/channels` | `{"channels":[{"name":"…","url":"…"}]}` |
| POST | `/api/play` | `{"id": 0}` |
| POST | `/api/stop` | – |
| POST | `/api/volume` | `{"action":"up"\|"down"\|"mute"}` |
| POST | `/api/shutdown` | – |
