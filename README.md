# TV Remote

Control the TV laptop (Linux Mint + Firefox over HDMI) from your phone.

- **Laptop** (`server/tvremote.py`): small Python server that uses only the standard library. When you pick a channel it closes all Firefox windows, reopens Firefox in **kiosk** mode on that channel's page, and puts the **video player itself in full screen**, so the TV shows only the video. It also controls the volume, stops playback and shuts the laptop down.
- **Phone** (`web/`): web app served by the laptop. It shows a grid of channels plus volume, stop and power buttons, and has an edit mode for the channel list. It works on Android and iOS. Add it to the home screen to use it like an app.

## Install (on the laptop)

```bash
git clone <this repo> ~/tv-pc-home-remote
cd ~/tv-pc-home-remote
./install.sh
```

The installer:
- adds an autostart entry, so the server starts when you log in to the desktop
- creates `~/.config/tv-remote/` (`config.json` holds the token and settings, `channels.txt` holds the channels)
- prints the URL for your phone, e.g. `http://192.168.1.50:8080/?t=AbC123...`, and a QR code if `qrencode` is installed

On the phone, open that URL in Chrome and choose **⋮ → Add to Home screen**. On an iPhone, use Safari and choose **Share → Add to Home Screen**.

> Tip: give the laptop a fixed IP (a DHCP reservation in your router) so the bookmark keeps working.

## Channels

You can edit the channels from the phone (**Editar** button), or by hand in `~/.config/tv-remote/channels.txt`:

```
RTP 1 | https://www.rtp.pt/play/direto/rtp1
CNN Portugal | https://cnnportugal.iol.pt/direto
```

Each line is `Name | URL`, and the file order is the grid order. Changes are picked up right away, with no restart needed.

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
| `shutdown_cmd` | `["systemctl","poweroff"]` | command used by the power button |
| `volume_step` | `5%` | volume step (uses `pactl`, falls back to `amixer`) |

Restart the server after changing settings. The simplest way is to run `./install.sh` again.

## Run manually / debug

```bash
python3 server/tvremote.py          # prints the phone URL
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
