# Gipsy on iPhone and iPad (no App Store, no Sideloadly)

Safari can save a web page to your Home Screen as an app. It gets its own
icon, opens full screen with no address bar, and keeps working with no
7-day re-signing. Gipsy Hub now hands out a web version of the Gipsy app,
so your iPhone and iPad can use it this way.

This is called a **PWA** (Progressive Web App): a website that installs and
behaves like an app.

```
iPhone / iPad (Safari, Home Screen icon)
        |  https://your-pc.your-tailnet.ts.net    <- secure address from Tailscale
        v
Tailscale on the PC  (tailscale serve: adds the https lock, passes everything on)
        v
Gipsy Hub  http://127.0.0.1:8765
   /          -> the web app (the files in gipsy_hub\web)
   /api/...   -> chat, voice, hearing, this week, ...
        v
Ollama (qwen3) on the RTX 3060
```

## Why the https address matters

Browsers only give a web page your **microphone** on a secure (`https://`)
address. Your hub speaks plain `http://`, so on `http://192.168.x.x:8765`
Gipsy can type and talk back, but it can't hear you.

Tailscale fixes this for free. `tailscale serve` gives your PC a real
`https://...ts.net` address with a proper certificate, and passes everything
through to the hub. It only works on devices signed in to your Tailscale, so
nobody else on the internet can reach it.

Bonus: the page comes from the hub itself, so the app already knows where
your PC is. You don't type any addresses into its Settings.

## One-time setup on the PC

1. **Update the hub code.** Download the newest code from GitHub (or
   `git pull`) into your hub folder, like for earlier updates.
2. **Install the web app.** Double-click `gipsy_hub\install_web_app.bat`.
   *What it does:* downloads `Gipsy-Web.zip` (built by GitHub Actions every
   time the app changes) and unzips it into `gipsy_hub\web`. Run it again
   whenever you want the newest version.
   (Docker setup: copy that `web` folder into `docker-data\hub\web`.)
3. **Restart the hub** (`start_hub.bat`). The window now says
   `iPhone / iPad: https://...` instead of `Web app: not installed`.
   Check it on the PC: open http://127.0.0.1:8765 and you should see
   "Tap to wake Gipsy".
4. **Install Tailscale** on the PC (tailscale.com/download) and sign in.
5. **Turn on secure addresses in Tailscale**, once: open
   login.tailscale.com/admin/dns, make sure **MagicDNS** is on, and under
   **HTTPS Certificates** click **Enable HTTPS**.
   *Why:* MagicDNS gives your PC a name instead of a number, and HTTPS
   lets Tailscale get a real certificate for that name.
6. **Share the hub over https.** Open PowerShell and run:

   ```powershell
   tailscale serve --bg 8765
   ```

   *What it does:* Tailscale listens on `https://<your-pc>.<your-tailnet>.ts.net`
   and passes every request to the hub on port 8765. `--bg` keeps it running
   in the background, even after a restart. It prints your address; write it
   down. `tailscale serve status` shows it again, and `tailscale serve reset`
   turns it off.

## On the iPhone and iPad

1. Install **Tailscale** from the App Store, sign in with the same account,
   and switch it on.
2. Open **Safari** and go to your `https://...ts.net` address.
   (It has to be Safari for step 5.)
3. Tap **Tap to wake Gipsy**. Allow the microphone when asked.
   *Why the tap:* Safari won't let a page play sound or use the mic until
   you touch it. One tap unlocks both, so Gipsy can answer out loud.
4. Say "Hey Gipsy" or tap the mic button to check it hears you.
5. Tap **Share** (the square with the arrow) and then **Add to Home Screen**,
   then **Add**. Gipsy's visor icon appears on your Home Screen.
6. From now on, open Gipsy from that icon. It opens full screen.

Settings, chat, voice picker, This week and the kaiju alert all work the
same as in the native app.

## Good to know

* **Tailscale must be on** on the phone, and the PC and hub must be running.
* **Gipsy listens only while it's open on screen.** iOS pauses web apps in
  the background (the Sideloaded app has the same limit).
* **Mic permission:** iOS may ask again each time you open Gipsy from the
  Home Screen. To stop that: Settings > Apps > Safari > Microphone > Allow.
* **If Gipsy is silent:** check the ring/silent switch and volume, then
  close Gipsy (swipe it away) and open it again.
* **Updating:** run `install_web_app.bat` again on the PC. The phone picks
  up the new version the next time Gipsy opens.
* **Home Wi-Fi address (`http://192.168...:8765`)** still opens the web app,
  and typing works, but use the https address to talk.
* **Hub key:** if you set `api_key` in config.json, enter it once in the web
  app's Settings.

## How it's built (for the write-up)

* `gipsy_app/web/` holds the PWA files: `manifest.json` (name, colours,
  icons, "open full screen") and `index.html` (iPhone icon, full-screen and
  notch settings, dark loading screen).
* `gipsy_app/lib/platform/` is where the browser version differs from the
  native apps. In the browser, recordings are `blob:` links instead of
  files, and sound plays through the Web Audio API, which Safari lets play
  later replies once the first tap has unlocked it.
* The hub serves the built app at `/` (`find_web_dir()` in `gipsy_hub.py`)
  and tells the phone to re-check files each time, so updates show up.
* `.github/workflows/web-app.yml` builds it on every change to the app and
  publishes `Gipsy-Web.zip` to the `web-app` release.
